import json
import threading
from typing import Any

import pytest
from soporte_auditor import (
    RedisStreamsFalso,
    RelojFalso,
    ValidacionFalsa,
    campos,
    evento_dict,
)

from auditor import ciclo
from auditor.cliente_validacion import ErrorValidacionRemota
from auditor.config import Config
from auditor.contracts import Decision
from auditor.repositorio import Repositorio


def _publicar(cola: RedisStreamsFalso, *eventos: dict[str, Any]) -> None:
    for evento in eventos:
        cola.xadd("auditoria", campos(evento))


def _correr(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
) -> ciclo.ResultadoCiclo:
    ciclo.asegurar_grupo(cola, config)
    return ciclo.un_ciclo(cola, config, repositorio, validacion, reloj)


def _regiones(repositorio: Repositorio, employee_id: str) -> dict[str, int]:
    return {h.region: h.conteo for h in repositorio.habitos(employee_id)}


# --- Reglas de §5.4 -----------------------------------------------------------


def test_region_habitual_no_informa_y_cuenta(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
) -> None:
    _publicar(
        cola, evento_dict("E-ASN-01", "norte", "a-1"), evento_dict("E-ASN-01", "norte", "a-2")
    )

    resultado = _correr(cola, config, repositorio, validacion, reloj)

    assert validacion.llamadas == []
    assert _regiones(repositorio, "E-ASN-01") == {"norte": 2}
    assert cola.pendientes() == []
    assert (resultado.eventos, resultado.anomalias) == (2, 0)


def test_region_nueva_informa_a_validacion(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
) -> None:
    _publicar(cola, evento_dict("E-ASN-01", "sur", "a-1"))

    resultado = _correr(cola, config, repositorio, validacion, reloj)

    assert [c.a_dict() for c in validacion.llamadas] == [
        {
            "evento_id": "a-1",
            "correlation_id": "c-a-1",
            "employee_id": "E-ASN-01",
            "session_id": "s-E-ASN-01",
            "accion": "CONSULTA_POLIZA",
            "region_consultada": "sur",
        }
    ]
    assert resultado.anomalias == 1
    assert cola.pendientes() == []


def test_alertar_incorpora_la_region_al_historial(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
) -> None:
    """E-ASM-01: `centro` está autorizado pero no es habitual (legítimo inusual)."""
    _publicar(
        cola, evento_dict("E-ASM-01", "centro", "a-1"), evento_dict("E-ASM-01", "centro", "a-2")
    )

    _correr(cola, config, repositorio, validacion, reloj)

    # Solo la primera se informa: al volverse habitual, la segunda se cuenta.
    assert len(validacion.llamadas) == 1
    assert _regiones(repositorio, "E-ASM-01") == {"centro": 2, "norte": 0}


def test_revocar_no_incorpora_y_cada_consulta_vuelve_a_informarse(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
) -> None:
    """Cada consulta extra del atacante produce un evento de seguridad más, que
    Reacción absorbe por idempotencia (métrica "eventos redundantes" de F9)."""
    _publicar(cola, *(evento_dict("E-ASN-01", "sur", f"a-{n}") for n in range(3)))

    resultado = _correr(cola, config, repositorio, validacion, reloj)

    assert [c.evento_id for c in validacion.llamadas] == ["a-0", "a-1", "a-2"]
    assert resultado.anomalias == 3
    assert _regiones(repositorio, "E-ASN-01") == {"norte": 0}


def test_evento_sin_region_se_ignora(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
) -> None:
    _publicar(cola, evento_dict("E-ASN-01", None, "a-1"))

    _correr(cola, config, repositorio, validacion, reloj)

    assert validacion.llamadas == []
    assert cola.pendientes() == []


def test_aprobacion_tambien_se_audita(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
) -> None:
    _publicar(cola, evento_dict("E-ASN-01", "centro", "a-1", accion="APROBACION_POLIZA"))

    _correr(cola, config, repositorio, validacion, reloj)

    assert validacion.llamadas[0].accion == "APROBACION_POLIZA"


# --- Fallos -------------------------------------------------------------------


def test_validacion_caida_deja_el_evento_pendiente_y_luego_se_completa(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
) -> None:
    _publicar(
        cola,
        evento_dict("E-ASN-01", "sur", "a-1"),
        evento_dict("E-ASN-02", "norte", "a-2"),
    )
    validacion.fallo = ErrorValidacionRemota("fallo de red", definitivo=False)

    caido = _correr(cola, config, repositorio, validacion, reloj)

    assert caido.fallo_transitorio is True
    assert not caido.repetir_sin_dormir
    # El lote se corta en el primer fallo: un timeout por ciclo, no uno por evento.
    assert len(validacion.llamadas) == 1
    assert cola.pendientes() == ["1-0", "2-0"]
    assert _regiones(repositorio, "E-ASN-02") == {"norte": 0}

    # Mientras los pendientes fallen, no se leen eventos nuevos.
    _publicar(cola, evento_dict("E-ASN-03", "norte", "a-3"))
    ciclo.un_ciclo(cola, config, repositorio, validacion, reloj)
    assert cola.sin_leer() == 1

    validacion.fallo = None
    recuperado = ciclo.un_ciclo(cola, config, repositorio, validacion, reloj)

    assert recuperado.fallo_transitorio is False
    assert recuperado.anomalias == 1
    assert cola.pendientes() == []
    assert cola.sin_leer() == 0
    assert _regiones(repositorio, "E-ASN-02") == {"norte": 1}
    assert _regiones(repositorio, "E-ASN-03") == {"norte": 1}


def test_fallo_definitivo_se_confirma_sin_reintentar(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
) -> None:
    """Un empleado que Validación no conoce (404): reintentar no lo arreglaría."""
    _publicar(cola, evento_dict("E-NADIE", "sur", "a-1"), evento_dict("E-ASN-01", "sur", "a-2"))

    resultado = _correr(cola, config, repositorio, validacion, reloj)

    assert [c.evento_id for c in validacion.llamadas] == ["a-1", "a-2"]
    assert resultado.anomalias == 1
    assert cola.pendientes() == []


@pytest.mark.parametrize(
    "crudo",
    [
        {"data": "no es json"},
        {"otro": "campo"},
        {"data": json.dumps(["no", "es", "objeto"])},
        {"data": json.dumps(evento_dict(actor={"employee_id": "E-ASN-01"}))},
        {"data": json.dumps({k: v for k, v in evento_dict().items() if k != "recurso"})},
        {"data": json.dumps(evento_dict(emitido_en="2026-09-21T14:02:10"))},
    ],
)
def test_mensaje_corrupto_se_confirma_y_no_bloquea(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
    crudo: dict[str, str],
) -> None:
    cola.xadd("auditoria", crudo)
    _publicar(cola, evento_dict("E-ASN-01", "sur", "a-2"))

    _correr(cola, config, repositorio, validacion, reloj)

    assert [c.evento_id for c in validacion.llamadas] == ["a-2"]
    assert cola.pendientes() == []


def test_evento_publicado_antes_de_crear_el_grupo_no_se_pierde(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
) -> None:
    _publicar(cola, evento_dict("E-ASN-01", "sur", "a-1"))  # antes de asegurar_grupo

    _correr(cola, config, repositorio, validacion, reloj)

    assert [c.evento_id for c in validacion.llamadas] == ["a-1"]


def test_grupo_desaparecido_se_recrea(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
) -> None:
    ciclo.asegurar_grupo(cola, config)
    cola.eliminar_grupo()
    _publicar(cola, evento_dict("E-ASN-01", "sur", "a-1"))

    ciclo.un_ciclo(cola, config, repositorio, validacion, reloj)  # recrea
    ciclo.un_ciclo(cola, config, repositorio, validacion, reloj)  # procesa

    assert [c.evento_id for c in validacion.llamadas] == ["a-1"]


def test_asegurar_grupo_es_idempotente(cola: RedisStreamsFalso, config: Config) -> None:
    ciclo.asegurar_grupo(cola, config)
    ciclo.asegurar_grupo(cola, config)


# --- Periodicidad y lotes -----------------------------------------------------


def test_lectura_no_bloquea_y_respeta_el_tamano_de_lote(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
) -> None:
    _correr(cola, config, repositorio, validacion, reloj)
    assert cola.lecturas == [("0", 100, None), (">", 100, None)]


class _ParadaTrasDormir(threading.Event):
    """Detiene el bucle la primera vez que intenta dormir, y registra cuándo."""

    def __init__(self, cola: RedisStreamsFalso) -> None:
        super().__init__()
        self.cola = cola
        self.esperas: list[tuple[float | None, int]] = []

    def wait(self, timeout: float | None = None) -> bool:
        self.esperas.append((timeout, self.cola.sin_leer()))
        self.set()
        return True


def test_lote_lleno_repite_sin_dormir_y_los_ciclos_no_se_solapan(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
) -> None:
    _publicar(cola, *(evento_dict("E-ASN-01", "norte", f"a-{n}") for n in range(250)))
    parar = _ParadaTrasDormir(cola)

    ciclo.bucle(cola, config, repositorio, validacion, parar)

    # 100 + 100 + 50: tres ciclos seguidos, en el mismo hilo, y solo al
    # vaciar el stream se duerme el periodo completo.
    assert parar.esperas == [(config.periodo_s, 0)]
    assert [desde for desde, _, _ in cola.lecturas].count(">") == 3
    assert _regiones(repositorio, "E-ASN-01") == {"norte": 250}
    assert cola.pendientes() == []


def test_con_validacion_caida_el_bucle_duerme_aunque_el_lote_venga_lleno(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
) -> None:
    _publicar(cola, *(evento_dict("E-ASN-01", "sur", f"a-{n}") for n in range(150)))
    validacion.fallo = ErrorValidacionRemota("timeout", definitivo=False)
    parar = _ParadaTrasDormir(cola)

    ciclo.bucle(cola, config, repositorio, validacion, parar)

    assert len(parar.esperas) == 1
    assert len(validacion.llamadas) == 1


def test_ciclo_terminado_se_registra(
    cola: RedisStreamsFalso,
    config: Config,
    repositorio: Repositorio,
    validacion: ValidacionFalsa,
    reloj: RelojFalso,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _publicar(cola, evento_dict("E-ASN-01", "sur", "a-1"), evento_dict("E-ASN-01", "norte", "a-2"))
    caplog.set_level("INFO", logger="auditor.ciclo")

    _correr(cola, config, repositorio, validacion, reloj)

    terminado = next(r for r in caplog.records if r.getMessage() == "ciclo_terminado")
    assert (terminado.__dict__["eventos"], terminado.__dict__["anomalias"]) == (2, 1)
    assert isinstance(terminado.__dict__["duracion_ms"], int)
    informada = next(r for r in caplog.records if r.getMessage() == "anomalia_informada")
    assert informada.__dict__["employee_id"] == "E-ASN-01"
    assert informada.__dict__["region"] == "sur"
    assert informada.__dict__["decision"] == Decision.REVOCAR.value
    assert informada.__dict__["latencia_deteccion_ms"] == 3000
