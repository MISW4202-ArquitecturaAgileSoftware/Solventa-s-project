"""Bucle consumidor: XREADGROUP -> calcular -> LPUSH -> XACK.

La réplica es deliberadamente tonta: no sabe que existe una votación, ni cuántas
réplicas hay, ni que su resultado se compara con nada. Lee un sobre completamente
determinado —Votación ya fijó `fecha_calculo`— y responde.
"""

import json
import logging
import threading
from time import perf_counter
from typing import Any

from redis import Redis
from redis.exceptions import ResponseError

from cotizador import faults
from cotizador.config import Config
from cotizador.contracts import (
    EstadoRespuesta,
    SobreRespuesta,
    SobreSolicitud,
)
from cotizador.structured_logging import contexto_correlacion

log = logging.getLogger(__name__)

#: Campo del stream que transporta el envelope serializado.
CAMPO = "data"


def asegurar_grupo(cliente: Redis, config: Config) -> None:
    """Crea el consumer group de esta réplica, de forma idempotente.

    Se crea en `$` (solo mensajes nuevos) y no en `0`. Con `0`, cada reinicio
    reprocesaría todo el stream retenido y ensuciaría las mediciones de latencia
    del experimento. El stack controlado arranca las réplicas antes de ejecutar
    cualquier prueba.
    """
    try:
        cliente.xgroup_create(
            name=config.stream_solicitudes,
            groupname=config.grupo,
            id="$",
            mkstream=True,
        )
        log.info("consumer group creado", extra={"grupo": config.grupo})
    except ResponseError as err:
        if "BUSYGROUP" not in str(err):
            raise
        log.info("consumer group ya existía", extra={"grupo": config.grupo})


def procesar(cliente: Redis, config: Config, mensaje_id: str, campos: dict[str, str]) -> None:
    """Calcula y deposita la respuesta de esta réplica."""
    sobre = SobreSolicitud.desde_dict(json.loads(campos[CAMPO]))

    with contexto_correlacion(sobre.correlation_id):
        inicio = perf_counter()
        try:
            resultado = faults.calcular(
                sobre.payload,
                sobre.fecha_calculo,
                config.tarifario_version,
                config.fault_mode,
            )
        except faults.FalloInyectado:
            # `crash`: la réplica no responde. No se hace XACK, igual que un
            # proceso que muriera a mitad: el mensaje queda pendiente y es
            # evidencia auditable de que esta réplica lo dejó sin atender.
            log.error("sin respuesta por fallo inyectado", extra={"modo": config.fault_mode})
            return
        except Exception as err:
            duracion = round((perf_counter() - inicio) * 1000)
            respuesta = SobreRespuesta(
                correlation_id=sobre.correlation_id,
                cotizador_id=config.cotizador_id,
                estado=EstadoRespuesta.ERROR,
                duracion_ms=duracion,
                error=str(err),
            )
            log.exception("cálculo fallido")
        else:
            duracion = round((perf_counter() - inicio) * 1000)
            respuesta = SobreRespuesta(
                correlation_id=sobre.correlation_id,
                cotizador_id=config.cotizador_id,
                estado=EstadoRespuesta.OK,
                duracion_ms=duracion,
                resultado=resultado,
            )
            log.info(
                "cotización calculada",
                extra={
                    "cotizador_id": config.cotizador_id,
                    "prima_mensual": str(resultado.prima_mensual),
                    "duracion_ms": duracion,
                },
            )

        clave = config.clave_respuestas(sobre.correlation_id)
        # Pipeline: el LPUSH y su expiración son una sola ida y vuelta. Sin la
        # expiración, cada lista que Votación abandonara sería una fuga.
        with cliente.pipeline(transaction=False) as tuberia:
            tuberia.lpush(clave, json.dumps(respuesta.a_dict(), ensure_ascii=False))
            tuberia.expire(clave, config.ttl_respuestas_s)
            tuberia.execute()

        cliente.xack(config.stream_solicitudes, config.grupo, mensaje_id)


def bucle(cliente: Redis, config: Config, parar: threading.Event) -> None:
    """Consume solicitudes hasta que se pida detener el proceso."""
    asegurar_grupo(cliente, config)
    log.info(
        "worker listo",
        extra={"cotizador_id": config.cotizador_id, "fault_mode": config.fault_mode},
    )

    while not parar.is_set():
        try:
            # redis-py no tipa con precisión el retorno de xreadgroup; anotarlo
            # como Any es más honesto que un cast que finja una garantía inexistente.
            lotes: Any = cliente.xreadgroup(
                groupname=config.grupo,
                consumername=config.consumidor,
                streams={config.stream_solicitudes: ">"},
                count=10,
                block=config.block_ms,
            )
        except ResponseError as err:
            # NOGROUP: el stream o el grupo desaparecieron bajo los pies del
            # worker (alguien vació Redis entre corridas del experimento). Sin
            # esto el proceso moría y solo lo levantaba `restart: unless-stopped`,
            # perdiendo mensajes durante el reinicio. Recrear el grupo y seguir
            # es más barato y deja constancia en el log.
            if "NOGROUP" not in str(err):
                raise
            log.warning("consumer group desaparecido, recreando", extra={"grupo": config.grupo})
            asegurar_grupo(cliente, config)
            continue
        for _stream, mensajes in lotes or []:
            for mensaje_id, campos in mensajes:
                try:
                    procesar(cliente, config, mensaje_id, campos)
                except Exception:
                    # Un mensaje corrupto no puede tumbar la réplica: se registra,
                    # se deja pendiente y se sigue con el siguiente.
                    log.exception("mensaje no procesable", extra={"mensaje_id": mensaje_id})

    log.info("bucle detenido")
