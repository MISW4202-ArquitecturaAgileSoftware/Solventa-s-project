"""Reacción: el proceso de contención (PLAN-IMPLEMENTACION.md §5.5).

Vive dentro del contenedor de Validación, como fija la vista de despliegue,
pero sigue siendo asíncrono: un hilo consume el stream `seguridad` que la API
de Validación publica, revoca y bloquea en Autenticación y registra la alerta.
La API y este hilo solo comparten la base SQLite y el cliente de Redis.

El bucle relee primero sus propios mensajes pendientes (`XREADGROUP` con id
`0`) antes de pedir mensajes nuevos (`>`): un evento que falló porque
Autenticación estaba caída se reintenta en la siguiente vuelta. Si el lote de
pendientes vuelve a fallar, la vuelta espera `BLOCK_MS` antes de reintentar,
para no convertir la relectura —que con id `0` nunca bloquea— en un bucle
caliente.
"""

import atexit
import json
import logging
import threading
from typing import Any, Protocol

from redis.exceptions import ResponseError

from validacion.cliente_autenticacion import ClienteAutenticacion, ErrorContencion
from validacion.config import Config
from validacion.contracts import (
    AccionSeguridad,
    Alerta,
    EventoSeguridad,
    ahora_utc,
    desde_iso_utc,
)
from validacion.errors import ErrorValidacion
from validacion.repositorio import Repositorio
from validacion.structured_logging import contexto_correlacion

log = logging.getLogger(__name__)

CAMPO = "data"


class ClienteRedisStreams(Protocol):
    """Lo que el consumidor necesita de `redis.Redis`: solo streams y grupos."""

    def xgroup_create(
        self,
        name: str,
        groupname: str,
        id: str,  # noqa: A002 -- nombre fijado por la API de Redis
        mkstream: bool = False,
    ) -> object: ...

    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: Any,
        count: int = 10,
        block: int | None = None,
    ) -> Any: ...

    def xack(self, name: str, groupname: str, mensaje_id: str, /) -> object: ...


def asegurar_grupo(cliente: ClienteRedisStreams, config: Config) -> None:
    """Crea el consumer group en `$` (solo lo nuevo), de forma idempotente."""
    try:
        cliente.xgroup_create(
            name=config.stream_seguridad, groupname=config.grupo_reaccion, id="$", mkstream=True
        )
        log.info("consumer group creado", extra={"grupo": config.grupo_reaccion})
    except ResponseError as err:
        if "BUSYGROUP" not in str(err):
            raise
        log.info("consumer group ya existía", extra={"grupo": config.grupo_reaccion})


def procesar_evento(
    repositorio: Repositorio, cliente_auth: ClienteAutenticacion, evento: EventoSeguridad
) -> None:
    """Regla de §5.5. Propaga `ErrorContencion` transitoria para que se reintente."""
    alerta = repositorio.alerta_por_clave(evento.session_id, evento.motivo)
    if alerta is not None and (
        alerta.accion is AccionSeguridad.ALERTAR or alerta.revocada_en is not None
    ):
        log.info(
            "alerta_duplicada",
            extra={
                "evento_id": evento.evento_id,
                "session_id": evento.session_id,
                "motivo": evento.motivo.value,
            },
        )
        return

    if alerta is None:
        alerta = Alerta(
            evento_id=evento.evento_id,
            session_id=evento.session_id,
            employee_id=evento.employee_id,
            motivo=evento.motivo,
            accion=evento.accion,
            correlation_id=evento.correlation_id,
            detalle=evento.detalle,
            recibida_en=ahora_utc(),
        )
        repositorio.insertar_alerta(alerta)

    if evento.accion is AccionSeguridad.REVOCAR:
        try:
            # Revocar PRIMERO: así una verificación de sesión concurrente ya
            # reporta REVOCADA antes de que el empleado quede bloqueado.
            revocacion = cliente_auth.revocar(
                evento.session_id, evento.motivo.value, evento.correlation_id, alerta.evento_id
            )
            bloqueo = cliente_auth.bloquear(
                evento.employee_id, evento.motivo.value, evento.correlation_id, alerta.evento_id
            )
        except ErrorContencion as err:
            log.error(
                "contencion_fallida_definitiva"
                if err.definitivo
                else "contencion_fallida_transitoria",
                extra={
                    "evento_id": alerta.evento_id,
                    "session_id": evento.session_id,
                    "motivo_error": str(err),
                },
            )
            if err.definitivo:
                return
            raise
        repositorio.marcar_alerta_contenida(
            alerta.evento_id,
            desde_iso_utc(revocacion.revocada_en),
            desde_iso_utc(bloqueo.bloqueado_en),
        )

    latencia_ms = round((ahora_utc() - evento.emitido_en).total_seconds() * 1000)
    log.info(
        "incidente_contenido",
        extra={
            "evento_id": alerta.evento_id,
            "employee_id": evento.employee_id,
            "session_id": evento.session_id,
            "motivo": evento.motivo.value,
            "accion": evento.accion.value,
            "latencia_ms": latencia_ms,
        },
    )


def _procesar_mensaje(
    cliente: ClienteRedisStreams,
    config: Config,
    repositorio: Repositorio,
    cliente_auth: ClienteAutenticacion,
    mensaje_id: str,
    campos: dict[str, str],
) -> bool:
    """Devuelve True si el mensaje quedó atendido (y por tanto confirmado con XACK)."""
    try:
        evento = EventoSeguridad.desde_dict(json.loads(campos[CAMPO]))
    except (json.JSONDecodeError, ErrorValidacion, KeyError, ValueError) as err:
        # Un mensaje corrupto no se arregla reintentando: se registra y se da
        # por atendido, para no convertirlo en un bucle caliente contra la
        # relectura de pendientes propios.
        log.error(
            "mensaje_no_procesable", extra={"mensaje_id": mensaje_id, "motivo_error": str(err)}
        )
        cliente.xack(config.stream_seguridad, config.grupo_reaccion, mensaje_id)
        return True

    with contexto_correlacion(evento.correlation_id):
        try:
            procesar_evento(repositorio, cliente_auth, evento)
        except ErrorContencion:
            return False
        except Exception:
            log.exception(
                "error inesperado procesando evento", extra={"evento_id": evento.evento_id}
            )
            cliente.xack(config.stream_seguridad, config.grupo_reaccion, mensaje_id)
            return True

    cliente.xack(config.stream_seguridad, config.grupo_reaccion, mensaje_id)
    return True


def _procesar_lote(
    cliente: ClienteRedisStreams,
    config: Config,
    repositorio: Repositorio,
    cliente_auth: ClienteAutenticacion,
    desde: str,
    block: int | None,
) -> bool:
    """Lee y procesa un lote. Devuelve True si algún mensaje falló de forma transitoria."""
    try:
        lotes: Any = cliente.xreadgroup(
            groupname=config.grupo_reaccion,
            consumername=config.consumidor_reaccion,
            streams={config.stream_seguridad: desde},
            count=10,
            block=block,
        )
    except ResponseError as err:
        if "NOGROUP" not in str(err):
            raise
        log.warning(
            "consumer group desaparecido, recreando", extra={"grupo": config.grupo_reaccion}
        )
        asegurar_grupo(cliente, config)
        return False

    hubo_fallo = False
    for _stream, mensajes in lotes or []:
        for mensaje_id, campos in mensajes:
            if not _procesar_mensaje(
                cliente, config, repositorio, cliente_auth, mensaje_id, campos
            ):
                hubo_fallo = True
    return hubo_fallo


def una_vuelta(
    cliente: ClienteRedisStreams,
    config: Config,
    repositorio: Repositorio,
    cliente_auth: ClienteAutenticacion,
) -> bool:
    """Pendientes propios primero y, si no fallaron, mensajes nuevos.

    Devuelve True si hubo al menos un fallo transitorio, para que quien llama
    espere `BLOCK_MS` antes de la siguiente vuelta.
    """
    if _procesar_lote(cliente, config, repositorio, cliente_auth, desde="0", block=None):
        return True
    return _procesar_lote(
        cliente, config, repositorio, cliente_auth, desde=">", block=config.block_ms
    )


def bucle(
    cliente: ClienteRedisStreams,
    config: Config,
    repositorio: Repositorio,
    cliente_auth: ClienteAutenticacion,
    parar: threading.Event,
) -> None:
    asegurar_grupo(cliente, config)
    log.info(
        "reacción lista",
        extra={"grupo": config.grupo_reaccion, "consumidor": config.consumidor_reaccion},
    )
    while not parar.is_set():
        try:
            if una_vuelta(cliente, config, repositorio, cliente_auth):
                parar.wait(config.block_ms / 1000)
        except Exception:
            # Redis caído u otro fallo de infraestructura: el hilo no muere;
            # espera y vuelve a intentar, igual que un worker con restart.
            log.exception("vuelta de reacción fallida")
            parar.wait(config.block_ms / 1000)
    log.info("reacción detenida")


def iniciar(
    cliente: ClienteRedisStreams,
    config: Config,
    repositorio: Repositorio,
    cliente_auth: ClienteAutenticacion,
) -> threading.Thread:
    """Arranca el hilo de Reacción dentro del proceso de la API."""
    parar = threading.Event()
    hilo = threading.Thread(
        target=bucle,
        args=(cliente, config, repositorio, cliente_auth, parar),
        name="reaccion",
        daemon=True,
    )
    atexit.register(parar.set)
    hilo.start()
    return hilo
