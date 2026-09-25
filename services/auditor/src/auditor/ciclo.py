"""Ciclo periódico de auditoría a posteriori (PLAN-IMPLEMENTACION.md §5.4).

Un solo hilo: los ciclos no se solapan por construcción. Cada ciclo relee
primero los mensajes pendientes propios (por si el ciclo anterior no pudo
confirmarlos) y luego los nuevos, sin bloquear -- bloquear aquí retrasaría la
señal de apagado. Si el lote vino lleno, el siguiente ciclo arranca de
inmediato; si no, el hilo duerme hasta el próximo `PERIODO_AUDITORIA_S`,
de forma interrumpible por SIGTERM.
"""

import json
import logging
import threading
from time import perf_counter
from typing import Any, Protocol

from redis.exceptions import ResponseError

from auditor.cliente_validacion import ErrorValidacionTransitoria, ProtocoloValidacion
from auditor.config import Config
from auditor.contracts import Decision, EventoAuditoria, ahora_utc
from auditor.repositorio import Repositorio
from auditor.structured_logging import contexto_correlacion

log = logging.getLogger(__name__)

#: Campo del stream que transporta el envelope serializado (igual en todo el monorepo).
CAMPO = "data"

Mensaje = tuple[str, dict[str, str]]


class ProtocoloRedis(Protocol):
    """Lo que el ciclo necesita de `redis.Redis`: solo streams y consumer groups.

    Una interfaz propia -- no la clase concreta -- porque el doble de pruebas
    (`tests/dobles.py`) no tiene por qué implementar el cliente completo.
    """

    # `id` repite el nombre del parámetro real de redis-py: el llamado a
    # `cliente.xgroup_create(..., id=...)` debe casar por nombre.
    def xgroup_create(
        self,
        name: str,
        groupname: str,
        id: str,  # noqa: A002
        mkstream: bool = ...,
    ) -> object: ...

    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        # `dict` es invariante en su tipo de clave: redis-py tipa `streams` con
        # una unión más ancha (bytes | str | memoryview) que la nuestra, y eso
        # basta para que la conformidad estructural del Protocol falle si se
        # anota como `dict[str, str]`.
        streams: Any,
        count: int | None = ...,
        block: int | None = ...,
    ) -> object: ...

    def xack(self, name: str, groupname: str, id: str) -> object: ...  # noqa: A002


def asegurar_grupo(cliente: ProtocoloRedis, config: Config) -> None:
    """Crea el consumer group de forma idempotente, en `$` (solo lo nuevo).

    Con `0` el primer arranque reprocesaría todo el stream retenido; el stack
    controlado arranca el Auditor antes de generar tráfico auditable.
    """
    try:
        cliente.xgroup_create(
            name=config.stream_auditoria, groupname=config.grupo, id="$", mkstream=True
        )
        log.info("consumer group creado", extra={"grupo": config.grupo})
    except ResponseError as err:
        if "BUSYGROUP" not in str(err):
            raise
        log.info("consumer group ya existía", extra={"grupo": config.grupo})


def _leer_lote(cliente: ProtocoloRedis, config: Config, id_lectura: str) -> list[Mensaje]:
    try:
        lotes: Any = cliente.xreadgroup(
            groupname=config.grupo,
            consumername=config.consumidor,
            streams={config.stream_auditoria: id_lectura},
            count=config.lote,
            block=None,
        )
    except ResponseError as err:
        if "NOGROUP" not in str(err):
            raise
        # El stream o el grupo desaparecieron bajo los pies del worker (p. ej.
        # alguien vació Redis entre corridas). Recrear y seguir es más barato
        # que morir y depender de `restart: unless-stopped`.
        log.warning("consumer group desaparecido, recreando", extra={"grupo": config.grupo})
        asegurar_grupo(cliente, config)
        return []

    mensajes: list[Mensaje] = []
    for _stream, lote in lotes or []:
        mensajes.extend(lote)
    return mensajes


def _procesar_evento(
    config: Config,
    repositorio: Repositorio,
    validacion: ProtocoloValidacion,
    evento: EventoAuditoria,
) -> tuple[bool, bool]:
    """Devuelve `(confirmar_xack, hubo_anomalia)`."""
    if evento.recurso.region is None:
        return True, False

    region = evento.recurso.region
    ahora = ahora_utc()
    if repositorio.tiene_region(evento.actor.employee_id, region):
        repositorio.incrementar(evento.actor.employee_id, region, ahora)
        return True, False

    try:
        decision = validacion.informar_anomalia(evento)
    except ErrorValidacionTransitoria as err:
        log.error(
            "fallo transitorio al informar la anomalía",
            extra={"employee_id": evento.actor.employee_id, "region": region, "motivo": str(err)},
        )
        return False, False

    if decision == Decision.ALERTAR:
        repositorio.incorporar(evento.actor.employee_id, region, ahora)

    log.info(
        "anomalia_informada",
        extra={
            "employee_id": evento.actor.employee_id,
            "session_id": evento.actor.session_id,
            "region": region,
            "decision": decision.value,
            "correlation_id": evento.correlation_id,
        },
    )
    return True, True


def un_ciclo(
    cliente: ProtocoloRedis,
    config: Config,
    repositorio: Repositorio,
    validacion: ProtocoloValidacion,
) -> int:
    """Ejecuta un ciclo completo. Devuelve el número de eventos leídos (para
    que quien lo llama decida si dormir o repetir de inmediato)."""
    inicio = perf_counter()
    eventos = 0
    anomalias = 0

    for id_lectura in ("0", ">"):
        for mensaje_id, campos in _leer_lote(cliente, config, id_lectura):
            eventos += 1
            try:
                evento = EventoAuditoria.desde_dict(json.loads(campos[CAMPO]))
            except Exception:
                # Un mensaje corrupto no se arregla reintentando: si quedara
                # pendiente, la relectura con id `0` lo reprocesaría en cada
                # ciclo para siempre. Se registra y se da por atendido.
                log.exception("mensaje no procesable", extra={"mensaje_id": mensaje_id})
                cliente.xack(config.stream_auditoria, config.grupo, mensaje_id)
                continue

            with contexto_correlacion(evento.correlation_id):
                try:
                    confirmar, hubo_anomalia = _procesar_evento(
                        config, repositorio, validacion, evento
                    )
                except Exception:
                    log.exception("evento no procesado", extra={"mensaje_id": mensaje_id})
                    continue

            if hubo_anomalia:
                anomalias += 1
            if confirmar:
                cliente.xack(config.stream_auditoria, config.grupo, mensaje_id)

    duracion_ms = round((perf_counter() - inicio) * 1000)
    log.info(
        "ciclo_terminado",
        extra={"eventos": eventos, "anomalias": anomalias, "duracion_ms": duracion_ms},
    )
    return eventos


def debe_dormir(eventos: int, config: Config) -> bool:
    """Un lote que vino lleno puede tener más mensajes detrás: no hay que dormir."""
    return eventos < config.lote


def bucle(
    cliente: ProtocoloRedis,
    config: Config,
    repositorio: Repositorio,
    validacion: ProtocoloValidacion,
    parar: threading.Event,
) -> None:
    asegurar_grupo(cliente, config)
    log.info(
        "worker listo",
        extra={"grupo": config.grupo, "periodo_auditoria_s": config.periodo_auditoria_s},
    )

    while not parar.is_set():
        eventos = un_ciclo(cliente, config, repositorio, validacion)
        if debe_dormir(eventos, config):
            parar.wait(config.periodo_auditoria_s)

    log.info("bucle detenido")
