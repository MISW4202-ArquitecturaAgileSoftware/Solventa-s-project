"""Bucle consumidor: XREADGROUP -> calcular -> LPUSH + EXPIRE -> XACK.

El worker recibe operaciones previamente autorizadas. No verifica JWT ni OTP.
El despliegue debe proteger a los productores mediante aislamiento y permisos
sobre Redis; una red interna no restringe por sí sola los comandos o claves.
"""

import json
import logging
import threading
from time import perf_counter
from typing import Any

from redis import Redis
from redis.exceptions import ResponseError

from gestion_cotizador.config import Config
from gestion_cotizador.contracts import (
    NOMBRE_SERVICIO,
    OPERACION_COTIZAR,
    CodigoRespuesta,
    EstadoRespuesta,
    SobreOperacion,
    SobreRespuesta,
)
from gestion_cotizador.errors import ErrorValidacion
from gestion_cotizador.pricing import calcular
from gestion_cotizador.structured_logging import contexto_correlacion

log = logging.getLogger(__name__)

#: Campo del stream que transporta el envelope serializado.
CAMPO = "data"


def asegurar_grupo(cliente: Redis, config: Config) -> None:
    """Crea el consumer group de este worker, de forma idempotente.

    En la primera creación se usa `$`: el productor debe esperar a que el
    grupo exista antes de publicar. Si el grupo ya existe, se conserva su
    posición. Los mensajes anteriores a la creación no se recuperan aquí.
    """
    try:
        cliente.xgroup_create(
            name=config.stream_cotizador,
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
    """Calcula y deposita la respuesta de este worker."""
    crudo: dict[str, Any] = json.loads(campos[CAMPO])
    correlation_id = crudo.get("correlation_id")
    if not isinstance(correlation_id, str) or not correlation_id:
        # Sin correlation_id no hay dónde depositar una respuesta: se trata
        # como el mensaje corrupto que es, y `bucle` lo deja pendiente.
        raise ErrorValidacion("correlation_id", "es obligatorio")

    with contexto_correlacion(correlation_id):
        inicio = perf_counter()
        try:
            sobre = SobreOperacion.desde_dict(crudo)
            if sobre.operacion != OPERACION_COTIZAR:
                raise ErrorValidacion(
                    "operacion", f"no soportada por {NOMBRE_SERVICIO}: {sobre.operacion!r}"
                )
            resultado = calcular(
                sobre.solicitud_cotizacion(), sobre.fecha_calculo(), config.tarifario_version
            )
        except ErrorValidacion as err:
            duracion = round((perf_counter() - inicio) * 1000)
            respuesta = SobreRespuesta(
                correlation_id=correlation_id,
                servicio=NOMBRE_SERVICIO,
                estado=EstadoRespuesta.ERROR,
                codigo=CodigoRespuesta.VALIDACION,
                duracion_ms=duracion,
                error=f"{err.campo} {err.detalle}",
            )
            log.warning("solicitud inválida", extra={"campo": err.campo})
        except Exception as err:
            duracion = round((perf_counter() - inicio) * 1000)
            respuesta = SobreRespuesta(
                correlation_id=correlation_id,
                servicio=NOMBRE_SERVICIO,
                estado=EstadoRespuesta.ERROR,
                codigo=CodigoRespuesta.INTERNO,
                duracion_ms=duracion,
                error=str(err),
            )
            log.exception("cálculo fallido")
        else:
            duracion = round((perf_counter() - inicio) * 1000)
            respuesta = SobreRespuesta(
                correlation_id=correlation_id,
                servicio=NOMBRE_SERVICIO,
                estado=EstadoRespuesta.OK,
                codigo=CodigoRespuesta.OK,
                duracion_ms=duracion,
                resultado=resultado,
            )
            log.info(
                "cotización calculada",
                extra={"prima_mensual": str(resultado.prima_mensual), "duracion_ms": duracion},
            )

        clave = config.clave_respuestas(correlation_id)
        # Pipeline: el LPUSH y su expiración son una sola ida y vuelta. Sin la
        # expiración, cada lista que Validación abandonara sería una fuga.
        with cliente.pipeline(transaction=False) as tuberia:
            tuberia.lpush(clave, json.dumps(respuesta.a_dict(), ensure_ascii=False))
            tuberia.expire(clave, config.ttl_respuestas_s)
            tuberia.execute()

        cliente.xack(config.stream_cotizador, config.grupo, mensaje_id)


def bucle(cliente: Redis, config: Config, parar: threading.Event) -> None:
    """Consume solicitudes hasta que se pida detener el proceso."""
    asegurar_grupo(cliente, config)
    log.info("worker listo", extra={"grupo": config.grupo, "consumidor": config.consumidor})

    while not parar.is_set():
        try:
            # redis-py no tipa con precisión el retorno de xreadgroup; anotarlo
            # como Any es más honesto que un cast que finja una garantía inexistente.
            lotes: Any = cliente.xreadgroup(
                groupname=config.grupo,
                consumername=config.consumidor,
                streams={config.stream_cotizador: ">"},
                count=10,
                block=config.block_ms,
            )
        except ResponseError as err:
            # NOGROUP: el stream o el grupo desaparecieron bajo los pies del
            # worker (alguien vació Redis entre corridas del experimento).
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
                    # Un mensaje corrupto no puede tumbar el worker: se
                    # registra, se deja pendiente y se sigue con el siguiente.
                    log.exception("mensaje no procesable", extra={"mensaje_id": mensaje_id})

    log.info("bucle detenido")
