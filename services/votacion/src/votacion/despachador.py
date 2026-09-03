"""Difusión de la solicitud y recolección de las respuestas.

Una sola escritura al stream: el fan-out lo hacen los consumer groups, uno por
réplica. Votación no sabe cuántos contenedores hay ni cómo se llaman.

La recolección tiene un presupuesto GLOBAL, no un timeout por respuesta. Con un
timeout por respuesta, tres respuestas lentas sumarían tres veces la espera y el
journey se saldría de ASR-12; con presupuesto global, el peor caso está acotado
por construcción.
"""

import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter

from redis import Redis

from votacion.contracts import SobreRespuesta, SobreSolicitud
from votacion import votador
from votacion.config import Config

log = logging.getLogger(__name__)

CAMPO = "data"


class Corte(StrEnum):
    """Por qué se dejó de esperar."""

    COMPLETA = "completa"
    QUORUM = "quorum"
    PRESUPUESTO = "presupuesto"


@dataclass(frozen=True, slots=True)
class Recoleccion:
    respuestas: list[SobreRespuesta]
    latencia_ms: int
    corte: Corte


def publicar(cliente: Redis, config: Config, sobre: SobreSolicitud) -> None:
    cliente.xadd(
        name=config.stream_solicitudes,
        fields={CAMPO: json.dumps(sobre.a_dict(), ensure_ascii=False)},
        maxlen=config.stream_maxlen,
        approximate=True,
    )


def recolectar(
    cliente: Redis,
    config: Config,
    correlation_id: str,
) -> Recoleccion:
    """Recoge respuestas hasta completar, alcanzar quórum + gracia, o agotar el
    presupuesto."""
    clave = config.clave_respuestas(correlation_id)
    inicio = perf_counter()
    limite_global = inicio + config.timeout_consenso_ms / 1000
    limite_gracia: float | None = None
    respuestas: list[SobreRespuesta] = []
    replicas_recibidas: set[str] = set()
    corte = Corte.PRESUPUESTO

    while len(respuestas) < config.replicas_esperadas:
        ahora = perf_counter()
        restante = limite_global - ahora
        if limite_gracia is not None:
            restante = min(restante, limite_gracia - ahora)
        if restante <= 0:
            corte = Corte.QUORUM if limite_gracia is not None else Corte.PRESUPUESTO
            break

        crudo = cliente.blpop([clave], timeout=restante)
        if crudo is None:
            corte = Corte.QUORUM if limite_gracia is not None else Corte.PRESUPUESTO
            break

        _, carga = crudo
        try:
            respuesta = SobreRespuesta.desde_dict(json.loads(carga))
        except Exception:
            # Una respuesta ilegible es una réplica menos, no un journey roto.
            log.exception("respuesta ilegible descartada")
            continue

        if respuesta.correlation_id != correlation_id:
            log.warning(
                "respuesta con correlación incorrecta descartada",
                extra={"cotizador_id": respuesta.cotizador_id},
            )
            continue
        if respuesta.cotizador_id in replicas_recibidas:
            log.warning(
                "respuesta duplicada descartada",
                extra={"cotizador_id": respuesta.cotizador_id},
            )
            continue

        replicas_recibidas.add(respuesta.cotizador_id)
        respuestas.append(respuesta)

        if limite_gracia is None and votador.acuerdo_maximo(respuestas) >= config.quorum:
            # Veredicto ya decidido. Se abre una ventana corta para las
            # rezagadas: no cambia la respuesta, pero permite ver y registrar a
            # la réplica divergente.
            limite_gracia = perf_counter() + config.gracia_tras_quorum_ms / 1000
    else:
        corte = Corte.COMPLETA

    return Recoleccion(
        respuestas=respuestas,
        latencia_ms=round((perf_counter() - inicio) * 1000),
        corte=corte,
    )


def limpiar(cliente: Redis, config: Config, correlation_id: str) -> None:
    """Borra la lista de respuestas ya consumida.

    Las rezagadas que lleguen después la recrearán, pero el `EXPIRE` que pone
    cada cotizador la retira sola.
    """
    cliente.delete(config.clave_respuestas(correlation_id))
