"""Bucle consumidor: XREADGROUP -> operar -> LPUSH + XADD auditoria -> XACK.

El worker es deliberadamente tonto: no sabe si el rol del actor era legítimo,
solo ejecuta la operación que el sobre pide y deja constancia auditable.
"""

import json
import logging
import threading
import uuid
from time import perf_counter
from typing import Any, Protocol

from redis.exceptions import ResponseError

from gestion_polizas.config import Config
from gestion_polizas.contracts import (
    EventoAuditoria,
    RecursoPoliza,
    SobreOperacion,
    SobreRespuesta,
    ahora_utc,
)
from gestion_polizas.operaciones import ejecutar
from gestion_polizas.repositorio import Repositorio
from gestion_polizas.structured_logging import contexto_correlacion

log = logging.getLogger(__name__)

#: Campo del stream que transporta el envelope serializado.
CAMPO = "data"


class ClienteCola(Protocol):
    """El recorte de la API de `redis.Redis` que este worker usa.

    Un `Protocol` en lugar del tipo concreto de `redis-py`: así un doble en
    memoria puede sustituirlo en tests sin heredar de nada. `fields` y
    `streams` quedan en `Any`: `redis-py` los tipa con alias genéricos
    (`dict` es invariante) que ningún `dict[str, str]` concreto satisface.
    """

    def pipeline(self, transaction: bool = ...) -> Any: ...
    def xadd(
        self,
        name: str,
        fields: Any,
        id: str = ...,  # noqa: A002 -- mismo nombre y posición que redis-py
        maxlen: int | None = ...,
        approximate: bool = ...,
    ) -> object: ...
    def xack(self, name: str, groupname: str, *ids: str) -> object: ...
    def xgroup_create(
        self,
        name: str,
        groupname: str,
        id: str = ...,  # noqa: A002 -- nombre del parámetro de redis-py, mismo que el call site
        mkstream: bool = ...,
    ) -> object: ...
    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: Any,
        count: int | None = ...,
        block: int | None = ...,
    ) -> object: ...


def asegurar_grupo(cliente: ClienteCola, config: Config) -> None:
    """Crea el consumer group de este worker, de forma idempotente.

    Al crearlo por primera vez se usa `$`: el productor debe esperar a
    que exista antes de publicar. Si ya existe, conserva su posición. Los
    mensajes anteriores a la creación no se recuperan aquí.
    """
    try:
        cliente.xgroup_create(
            name=config.stream_polizas,
            groupname=config.grupo,
            id="$",
            mkstream=True,
        )
        log.info("consumer group creado", extra={"grupo": config.grupo})
    except ResponseError as err:
        if "BUSYGROUP" not in str(err):
            raise
        log.info("consumer group ya existía", extra={"grupo": config.grupo})


def procesar(
    cliente: ClienteCola,
    config: Config,
    repositorio: Repositorio,
    mensaje_id: str,
    campos: dict[str, str],
) -> None:
    """Resuelve un mensaje del stream: responde y audita, siempre en ese orden."""
    sobre = SobreOperacion.desde_dict(json.loads(campos[CAMPO]))

    with contexto_correlacion(sobre.correlation_id):
        inicio = perf_counter()
        resultado = ejecutar(repositorio, sobre, ahora_utc())
        duracion = round((perf_counter() - inicio) * 1000)

        respuesta = SobreRespuesta(
            correlation_id=sobre.correlation_id,
            estado=resultado.estado,
            codigo=resultado.codigo,
            duracion_ms=duracion,
            resultado=resultado.resultado,
            error=resultado.error,
        )
        evento = EventoAuditoria(
            evento_id=str(uuid.uuid7()),
            correlation_id=sobre.correlation_id,
            emitido_en=ahora_utc(),
            actor=sobre.actor,
            accion=resultado.accion,
            recurso=RecursoPoliza(
                poliza_id=resultado.poliza_id,
                region=resultado.region,
                cliente_id=resultado.cliente_id,
            ),
            # `codigo` ya es "OK" en el camino feliz, así que también sirve
            # como el resultado auditado sin bifurcar sobre `estado`.
            resultado=resultado.codigo.value,
        )

        clave = config.clave_respuestas(sobre.correlation_id)
        # Pipeline: el LPUSH y su expiración son una sola ida y vuelta. Sin la
        # expiración, cada lista que Validación abandonara sería una fuga.
        with cliente.pipeline(transaction=False) as tuberia:
            tuberia.lpush(clave, json.dumps(respuesta.a_dict(), ensure_ascii=False))
            tuberia.expire(clave, config.ttl_respuestas_s)
            tuberia.execute()

        cliente.xadd(
            config.stream_auditoria,
            {CAMPO: json.dumps(evento.a_dict(), ensure_ascii=False)},
            maxlen=config.stream_maxlen,
            approximate=True,
        )

        log.info(
            "operación resuelta",
            extra={
                "operacion": sobre.operacion,
                "codigo": resultado.codigo.value,
                "duracion_ms": duracion,
            },
        )

        cliente.xack(config.stream_polizas, config.grupo, mensaje_id)


def bucle(
    cliente: ClienteCola, config: Config, repositorio: Repositorio, parar: threading.Event
) -> None:
    """Consume operaciones hasta que se pida detener el proceso."""
    asegurar_grupo(cliente, config)
    log.info("worker listo", extra={"grupo": config.grupo, "consumidor": config.consumidor})

    while not parar.is_set():
        try:
            # redis-py no tipa con precisión el retorno de xreadgroup; anotarlo
            # como Any es más honesto que un cast que finja una garantía inexistente.
            lotes: Any = cliente.xreadgroup(
                groupname=config.grupo,
                consumername=config.consumidor,
                streams={config.stream_polizas: ">"},
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
                    procesar(cliente, config, repositorio, mensaje_id, campos)
                except Exception:
                    # Un mensaje corrupto no puede tumbar el worker: se
                    # registra, se deja pendiente y se sigue con el siguiente.
                    log.exception("mensaje no procesable", extra={"mensaje_id": mensaje_id})

    log.info("bucle detenido")
