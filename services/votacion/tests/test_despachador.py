"""Recolección: presupuesto global, corte por quórum y ventana de gracia.

Se usa un doble de Redis en vez del real porque lo que se prueba es la política
de espera, y con un Redis de verdad los tiempos dependerían de la máquina.
"""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from time import perf_counter
from typing import Any

import pytest

from votacion.contracts import (
    EstadoRespuesta,
    ResultadoCotizacion,
    SobreRespuesta,
    SobreSolicitud,
    SolicitudCotizacion,
    ahora_utc,
)
from votacion.config import Config
from votacion.despachador import Corte, publicar, recolectar

FECHA_CALCULO = date(2026, 8, 31)


class RedisDoble:
    """Doble mínimo: sirve respuestas encoladas y registra los XADD.

    Cada elemento de `guion` es un sobre a devolver, o None para simular que el
    BLPOP venció sin nada. Los `None` son lo que permite probar la gracia y el
    presupuesto sin depender del reloj de la máquina.
    """

    def __init__(self, guion: list[SobreRespuesta | None]) -> None:
        self.guion = list(guion)
        self.publicados: list[dict[str, Any]] = []
        self.borrados: list[str] = []
        self.esperas: list[float] = []

    def xadd(self, name: str, fields: dict[str, str], **_kw: Any) -> str:
        self.publicados.append({"stream": name, "fields": fields})
        return "1-0"

    def blpop(self, claves: list[str], timeout: float) -> tuple[str, str] | None:
        self.esperas.append(timeout)
        if not self.guion:
            return None
        siguiente = self.guion.pop(0)
        if siguiente is None:
            return None
        return (claves[0], json.dumps(siguiente.a_dict()))

    def delete(self, clave: str) -> int:
        self.borrados.append(clave)
        return 1


@pytest.fixture
def config() -> Config:
    return Config(
        redis_url="redis://x",
        stream_solicitudes="cot:req",
        prefijo_respuestas="cot:resp",
        log_level="WARNING",
        replicas_esperadas=3,
        quorum=2,
        timeout_consenso_ms=250,
        gracia_tras_quorum_ms=25,
        stream_maxlen=10000,
        expose_consensus=True,
        url_gestion_errores="http://ge:8000",
        timeout_reporte_s=2.0,
        hilos_reporte=2,
    )


def _respuesta(cotizador_id: str, resultado: ResultadoCotizacion) -> SobreRespuesta:
    return SobreRespuesta(
        correlation_id="cid",
        cotizador_id=cotizador_id,
        estado=EstadoRespuesta.OK,
        duracion_ms=1,
        resultado=resultado,
    )


def _con_prima(base: ResultadoCotizacion, prima: str) -> ResultadoCotizacion:
    mensual = Decimal(prima)
    return replace(base, prima_mensual=mensual, prima_anual=mensual * 12)


def test_publica_una_sola_vez(config: Config, solicitud: SolicitudCotizacion) -> None:
    """El fan-out lo hacen los consumer groups, no tres escrituras."""
    doble = RedisDoble([])
    sobre = SobreSolicitud(
        correlation_id="cid",
        emitido_en=ahora_utc(),
        fecha_calculo=FECHA_CALCULO,
        payload=solicitud,
    )
    publicar(doble, config, sobre)  # type: ignore[arg-type]

    assert len(doble.publicados) == 1
    assert doble.publicados[0]["stream"] == "cot:req"


def test_recoge_las_tres_y_corta_por_completa(
    config: Config, solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    doble = RedisDoble([_respuesta("A", sano), _respuesta("B", sano), _respuesta("C", sano)])
    recoleccion = recolectar(doble, config, "cid")  # type: ignore[arg-type]

    assert len(recoleccion.respuestas) == 3
    assert recoleccion.corte is Corte.COMPLETA


def test_la_gracia_acota_la_espera_de_la_rezagada(
    config: Config, solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    """Con quórum en A y C, la tercera no puede costar el presupuesto entero.

    Es lo que hace que una réplica `slow` (400 ms) o `crash` no saque el journey
    de los 300 ms de ASR-12.
    """
    doble = RedisDoble([_respuesta("A", sano), _respuesta("C", sano)])
    inicio = perf_counter()
    recoleccion = recolectar(doble, config, "cid")  # type: ignore[arg-type]
    transcurrido = (perf_counter() - inicio) * 1000

    assert len(recoleccion.respuestas) == 2
    assert recoleccion.corte is Corte.QUORUM
    # Muy por debajo del presupuesto de 250 ms.
    assert transcurrido < 100


def test_la_ultima_espera_se_recorta_a_la_gracia(
    config: Config, solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    """Tras el quórum, el BLPOP siguiente no puede pedir los 250 ms."""
    doble = RedisDoble([_respuesta("A", sano), _respuesta("C", sano), None])
    recolectar(doble, config, "cid")  # type: ignore[arg-type]

    assert doble.esperas[0] == pytest.approx(0.25, abs=0.01)
    assert doble.esperas[-1] <= 0.025 + 1e-6


def test_sin_quorum_se_espera_el_presupuesto_completo(
    config: Config, solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    """Dos respuestas que NO coinciden no abren la gracia: aún puede llegar la
    tercera y desempatar."""
    doble = RedisDoble(
        [_respuesta("A", sano), _respuesta("B", _con_prima(sano, "103900.67")), None]
    )
    recoleccion = recolectar(doble, config, "cid")  # type: ignore[arg-type]

    assert recoleccion.corte is Corte.PRESUPUESTO
    assert doble.esperas[-1] > 0.025


def test_sin_respuestas_corta_por_presupuesto(
    config: Config, solicitud: SolicitudCotizacion
) -> None:
    doble = RedisDoble([None])
    recoleccion = recolectar(doble, config, "cid")  # type: ignore[arg-type]

    assert recoleccion.respuestas == []
    assert recoleccion.corte is Corte.PRESUPUESTO


def test_una_respuesta_ilegible_no_rompe_la_recoleccion(
    config: Config, solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    class ConBasura(RedisDoble):
        def blpop(self, claves: list[str], timeout: float) -> tuple[str, str] | None:
            if not self.esperas:
                self.esperas.append(timeout)
                return (claves[0], "{no soy json")
            return super().blpop(claves, timeout)

    doble = ConBasura([_respuesta("A", sano), _respuesta("C", sano)])
    recoleccion = recolectar(doble, config, "cid")  # type: ignore[arg-type]

    assert len(recoleccion.respuestas) == 2


def test_una_replica_duplicada_no_forma_quorum(
    config: Config, solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    doble = RedisDoble([_respuesta("A", sano), _respuesta("A", sano), None])

    recoleccion = recolectar(doble, config, "cid")  # type: ignore[arg-type]

    assert [r.cotizador_id for r in recoleccion.respuestas] == ["A"]
    assert recoleccion.corte is Corte.PRESUPUESTO


def test_una_respuesta_de_otro_journey_se_descarta(
    config: Config, solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    ajena = replace(_respuesta("A", sano), correlation_id="otra-correlacion")
    doble = RedisDoble([ajena, _respuesta("B", sano), None])

    recoleccion = recolectar(doble, config, "cid")  # type: ignore[arg-type]

    assert [r.cotizador_id for r in recoleccion.respuestas] == ["B"]


def test_limpiar_borra_la_lista(config: Config) -> None:
    from votacion.despachador import limpiar

    doble = RedisDoble([])
    limpiar(doble, config, "cid")  # type: ignore[arg-type]

    assert doble.borrados == ["cot:resp:cid"]
