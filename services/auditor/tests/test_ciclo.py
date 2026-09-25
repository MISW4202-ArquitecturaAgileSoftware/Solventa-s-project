import json
import threading
from dataclasses import replace

import pytest
from dobles import RedisFalso, ValidacionFalsa

from auditor import ciclo
from auditor.config import Config
from auditor.contracts import Accion, Decision, ahora_utc
from auditor.repositorio import Repositorio


def _campos_evento(
    *,
    evento_id: str = "019a",
    correlation_id: str = "019b",
    employee_id: str = "E-ASN-01",
    session_id: str = "019c",
    rol: str = "asesor",
    accion: str = "CONSULTA_POLIZA",
    poliza_id: str = "POL-SUR-003",
    region: str | None = "sur",
    cliente_id: str | None = "CLI-SUR-003",
    resultado: str = "OK",
) -> dict[str, str]:
    return {
        "data": json.dumps(
            {
                "evento_id": evento_id,
                "correlation_id": correlation_id,
                "tipo": "operacion.auditada",
                "version": "1",
                "emitido_en": "2026-09-21T14:02:10.418Z",
                "actor": {"employee_id": employee_id, "session_id": session_id, "rol": rol},
                "accion": accion,
                "recurso": {
                    "tipo": "poliza",
                    "poliza_id": poliza_id,
                    "region": region,
                    "cliente_id": cliente_id,
                },
                "resultado": resultado,
            }
        )
    }


@pytest.fixture
def redis_falso(config: Config) -> RedisFalso:
    cliente = RedisFalso()
    ciclo.asegurar_grupo(cliente, config)
    return cliente


def test_region_habitual_no_informa_e_incrementa_el_conteo(
    config: Config, repositorio: Repositorio, redis_falso: RedisFalso
) -> None:
    repositorio.incorporar("E-ASN-01", "norte", ahora_utc())
    validacion = ValidacionFalsa()
    redis_falso.publicar(config.stream_auditoria, _campos_evento(region="norte"))

    eventos = ciclo.un_ciclo(redis_falso, config, repositorio, validacion)

    assert eventos == 1
    assert validacion.llamadas == []
    entrada = repositorio.entrada("E-ASN-01", "norte")
    assert entrada is not None
    assert entrada.conteo == 2
    assert redis_falso._pendientes[(config.stream_auditoria, config.grupo, config.consumidor)] == {}


def test_region_nueva_se_informa(
    config: Config, repositorio: Repositorio, redis_falso: RedisFalso
) -> None:
    validacion = ValidacionFalsa(decisiones={("E-ASN-01", "sur"): Decision.ALERTAR})
    redis_falso.publicar(config.stream_auditoria, _campos_evento(region="sur"))

    eventos = ciclo.un_ciclo(redis_falso, config, repositorio, validacion)

    assert eventos == 1
    assert len(validacion.llamadas) == 1
    llamada = validacion.llamadas[0]
    assert llamada.actor.employee_id == "E-ASN-01"
    assert llamada.recurso.region == "sur"
    assert llamada.accion == Accion.CONSULTA_POLIZA


def test_alertar_incorpora_la_region_y_la_segunda_consulta_ya_no_informa(
    config: Config, repositorio: Repositorio, redis_falso: RedisFalso
) -> None:
    validacion = ValidacionFalsa(decisiones={("E-ASN-01", "centro"): Decision.ALERTAR})
    redis_falso.publicar(config.stream_auditoria, _campos_evento(region="centro"))
    ciclo.un_ciclo(redis_falso, config, repositorio, validacion)

    assert repositorio.tiene_region("E-ASN-01", "centro")
    assert len(validacion.llamadas) == 1

    redis_falso.publicar(config.stream_auditoria, _campos_evento(region="centro"))
    ciclo.un_ciclo(redis_falso, config, repositorio, validacion)

    assert len(validacion.llamadas) == 1
    entrada = repositorio.entrada("E-ASN-01", "centro")
    assert entrada is not None
    assert entrada.conteo == 2


def test_revocar_no_incorpora_la_region(
    config: Config, repositorio: Repositorio, redis_falso: RedisFalso
) -> None:
    validacion = ValidacionFalsa(decisiones={("E-ASN-01", "sur"): Decision.REVOCAR})
    redis_falso.publicar(config.stream_auditoria, _campos_evento(region="sur"))

    ciclo.un_ciclo(redis_falso, config, repositorio, validacion)

    assert not repositorio.tiene_region("E-ASN-01", "sur")


def test_evento_sin_region_hace_xack_sin_informar(
    config: Config, repositorio: Repositorio, redis_falso: RedisFalso
) -> None:
    validacion = ValidacionFalsa()
    redis_falso.publicar(config.stream_auditoria, _campos_evento(region=None, cliente_id=None))

    eventos = ciclo.un_ciclo(redis_falso, config, repositorio, validacion)

    assert eventos == 1
    assert validacion.llamadas == []
    assert redis_falso._pendientes[(config.stream_auditoria, config.grupo, config.consumidor)] == {}


def test_fallo_transitorio_no_hace_xack_y_se_reprocesa(
    config: Config, repositorio: Repositorio, redis_falso: RedisFalso
) -> None:
    validacion = ValidacionFalsa(fallar_para={"E-ASN-01"})
    redis_falso.publicar(config.stream_auditoria, _campos_evento(region="sur"))

    eventos_primer_ciclo = ciclo.un_ciclo(redis_falso, config, repositorio, validacion)

    assert eventos_primer_ciclo == 1
    assert len(validacion.llamadas) == 1
    assert not repositorio.tiene_region("E-ASN-01", "sur")
    pendientes = redis_falso._pendientes[(config.stream_auditoria, config.grupo, config.consumidor)]
    assert len(pendientes) == 1

    validacion.fallar_para.clear()
    validacion.decisiones[("E-ASN-01", "sur")] = Decision.ALERTAR
    eventos_segundo_ciclo = ciclo.un_ciclo(redis_falso, config, repositorio, validacion)

    assert eventos_segundo_ciclo == 1
    assert len(validacion.llamadas) == 2
    assert repositorio.tiene_region("E-ASN-01", "sur")
    assert redis_falso._pendientes[(config.stream_auditoria, config.grupo, config.consumidor)] == {}


def test_un_ciclo_devuelve_el_numero_de_eventos_procesados(
    config: Config, repositorio: Repositorio, redis_falso: RedisFalso
) -> None:
    validacion = ValidacionFalsa()
    for region in ("norte", "norte", "norte"):
        redis_falso.publicar(config.stream_auditoria, _campos_evento(region=region))

    eventos = ciclo.un_ciclo(redis_falso, config, repositorio, validacion)

    assert eventos == 3


def test_debe_dormir_solo_cuando_el_lote_no_vino_lleno(config: Config) -> None:
    config_lote_corto = replace(config, lote=2)
    assert ciclo.debe_dormir(1, config_lote_corto) is True
    assert ciclo.debe_dormir(2, config_lote_corto) is False
    assert ciclo.debe_dormir(3, config_lote_corto) is False


def test_mensaje_corrupto_no_tumba_el_ciclo_y_se_confirma(
    config: Config, repositorio: Repositorio, redis_falso: RedisFalso
) -> None:
    validacion = ValidacionFalsa()
    redis_falso.publicar(config.stream_auditoria, {"data": "{no es json"})

    eventos = ciclo.un_ciclo(redis_falso, config, repositorio, validacion)

    assert eventos == 1
    pendientes = redis_falso._pendientes[(config.stream_auditoria, config.grupo, config.consumidor)]
    assert len(pendientes) == 0
    assert ciclo.un_ciclo(redis_falso, config, repositorio, validacion) == 0


def test_asegurar_grupo_es_idempotente(config: Config) -> None:
    cliente = RedisFalso()
    ciclo.asegurar_grupo(cliente, config)
    ciclo.asegurar_grupo(cliente, config)
    assert (config.stream_auditoria, config.grupo) in cliente._grupos


def test_grupo_desaparecido_se_recrea_sin_tumbar_el_ciclo(
    config: Config, repositorio: Repositorio, redis_falso: RedisFalso
) -> None:
    validacion = ValidacionFalsa()
    redis_falso._grupos.discard((config.stream_auditoria, config.grupo))

    eventos = ciclo.un_ciclo(redis_falso, config, repositorio, validacion)

    assert eventos == 0
    assert (config.stream_auditoria, config.grupo) in redis_falso._grupos


def test_bucle_no_duerme_mientras_el_lote_viene_lleno(
    config: Config, repositorio: Repositorio, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_lote_uno = replace(config, lote=1)
    cliente = RedisFalso()
    ciclo.asegurar_grupo(cliente, config_lote_uno)
    validacion = ValidacionFalsa()
    cliente.publicar(
        config_lote_uno.stream_auditoria, _campos_evento(region="norte", evento_id="e1")
    )
    cliente.publicar(
        config_lote_uno.stream_auditoria, _campos_evento(region="norte", evento_id="e2")
    )

    parar = threading.Event()
    esperas: list[float | None] = []
    espera_original = parar.wait

    def espera_falsa(timeout: float | None = None) -> bool:
        esperas.append(timeout)
        parar.set()
        return espera_original(0)

    monkeypatch.setattr(parar, "wait", espera_falsa)

    ciclo.bucle(cliente, config_lote_uno, repositorio, validacion, parar)

    # Dos eventos con LOTE=1 fuerzan dos ciclos sin dormir (uno por evento) y
    # solo el tercer ciclo, ya vacío, duerme -- una sola espera registrada.
    assert esperas == [config_lote_uno.periodo_auditoria_s]
    clave_consumidor = (
        config_lote_uno.stream_auditoria,
        config_lote_uno.grupo,
        config_lote_uno.consumidor,
    )
    assert cliente._pendientes[clave_consumidor] == {}
