"""El ciclo del Auditor (PLAN-IMPLEMENTACION.md §5.4): detección a posteriori.

Cada ciclo:

1. Relee sus propios pendientes (`XREADGROUP … 0`): eventos entregados en un
   ciclo anterior cuya anomalía no se pudo informar porque Validación no
   respondió. `>` nunca los volvería a entregar, así que sin este paso "se
   reintenta en el ciclo siguiente" no sería verdad.
2. Si los pendientes se resolvieron, lee eventos nuevos (`>`), sin bloquear.
3. Por cada evento: sin región → se ignora; región habitual → se cuenta; región
   nueva → `POST validacion/v1/anomalias`, y si la decisión es `ALERTAR` la
   región pasa al historial (`REVOCAR` no: la próxima consulta del atacante
   vuelve a informarse y Reacción absorbe el duplicado).

Ante el primer fallo transitorio de Validación el lote se corta: el resto de
eventos ya entregados queda pendiente y vuelve en el ciclo siguiente. Así, con
Validación caída, un ciclo cuesta un timeout y no uno por evento.

Un solo hilo: los ciclos no se solapan por construcción. Un lote lleno repite
el ciclo sin dormir; si no, se duerme `PERIODO_AUDITORIA_S`.
"""

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from time import perf_counter
from typing import Any, Protocol

from redis.exceptions import ResponseError

from auditor.cliente_validacion import ClienteValidacion, ErrorValidacionRemota
from auditor.config import Config
from auditor.contracts import (
    CuerpoAnomalia,
    Decision,
    ErrorEventoInvalido,
    EventoAuditoria,
    ahora_utc,
)
from auditor.repositorio import Repositorio
from auditor.structured_logging import contexto_correlacion

log = logging.getLogger(__name__)

#: Campo del stream que transporta el evento serializado.
CAMPO = "data"

Reloj = Callable[[], datetime]


class ClienteCola(Protocol):
    """El recorte de `redis.Redis` que usa el Auditor: solo streams y grupos.

    `streams` queda en `Any`: redis-py lo tipa con alias genéricos (`dict` es
    invariante) que ningún `dict[str, str]` concreto satisface.
    """

    def xgroup_create(
        self,
        name: str,
        groupname: str,
        id: str = ...,  # noqa: A002 -- nombre del parámetro en redis-py
        mkstream: bool = ...,
    ) -> object: ...

    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: Any,
        count: int | None = ...,
        block: int | None = ...,
    ) -> Any: ...

    def xack(self, name: str, groupname: str, *ids: str) -> object: ...


class _Destino(Enum):
    CONFIRMADO = auto()
    PENDIENTE = auto()


@dataclass(frozen=True, slots=True)
class ResultadoLote:
    eventos: int = 0
    anomalias: int = 0
    lleno: bool = False
    fallo_transitorio: bool = False


@dataclass(frozen=True, slots=True)
class ResultadoCiclo:
    eventos: int
    anomalias: int
    #: Algún lote vino lleno: quedan eventos por leer, no hay que dormir.
    lleno: bool
    #: Validación no respondió: hay eventos pendientes para el ciclo siguiente.
    fallo_transitorio: bool
    duracion_ms: int

    @property
    def repetir_sin_dormir(self) -> bool:
        return self.lleno and not self.fallo_transitorio


def asegurar_grupo(cliente: ClienteCola, config: Config) -> None:
    """Crea el consumer group de forma idempotente, desde el PRINCIPIO del
    stream (`0`, no `$`): un detector no debe perder eventos publicados antes
    de su primer arranque. Si el grupo ya existe conserva su posición."""
    try:
        cliente.xgroup_create(
            name=config.stream_auditoria, groupname=config.grupo, id="0", mkstream=True
        )
        log.info("consumer group creado", extra={"grupo": config.grupo})
    except ResponseError as err:
        if "BUSYGROUP" not in str(err):
            raise
        log.info("consumer group ya existía", extra={"grupo": config.grupo})


def _evaluar(
    evento: EventoAuditoria,
    repositorio: Repositorio,
    validacion: ClienteValidacion,
    reloj: Reloj,
) -> tuple[_Destino, bool]:
    """Aplica §5.4 a un evento. Devuelve su destino y si se informó una anomalía."""
    if evento.region is None:
        log.debug("evento_sin_region", extra={"evento_id": evento.evento_id})
        return _Destino.CONFIRMADO, False

    region = evento.region
    if repositorio.registrar_observacion(evento.employee_id, region, reloj()):
        return _Destino.CONFIRMADO, False

    try:
        decision = validacion.informar_anomalia(CuerpoAnomalia.desde_evento(evento, region))
    except ErrorValidacionRemota as err:
        extra = {
            "evento_id": evento.evento_id,
            "employee_id": evento.employee_id,
            "region": region,
            "motivo_error": str(err),
        }
        if err.definitivo:
            # Reintentar no lo arreglará (p. ej. empleado desconocido para
            # Validación): se confirma para no bloquear el stream.
            log.error("anomalia_no_informable", extra=extra)
            return _Destino.CONFIRMADO, False
        log.warning("validacion_no_disponible", extra=extra)
        return _Destino.PENDIENTE, False

    if decision is Decision.ALERTAR:
        repositorio.incorporar(evento.employee_id, region, reloj())

    log.info(
        "anomalia_informada",
        extra={
            "evento_id": evento.evento_id,
            "employee_id": evento.employee_id,
            "session_id": evento.session_id,
            "region": region,
            "decision": decision.value,
            # Desde que gestion-polizas publicó el evento hasta que Validación
            # decidió: la parte de la ventana de exposición de ASR-31 que no
            # es espera del periodo.
            "latencia_deteccion_ms": round((reloj() - evento.emitido_en).total_seconds() * 1000),
        },
    )
    return _Destino.CONFIRMADO, True


def _procesar_mensaje(
    mensaje_id: str,
    campos: dict[str, str],
    repositorio: Repositorio,
    validacion: ClienteValidacion,
    reloj: Reloj,
) -> tuple[_Destino, bool]:
    try:
        evento = EventoAuditoria.desde_dict(json.loads(campos[CAMPO]))
    except (KeyError, ValueError, ErrorEventoInvalido) as err:
        # Un mensaje corrupto no se arregla reintentando y, como los pendientes
        # se releen primero, dejarlo sin confirmar bloquearía todo el stream.
        # Incluye el pendiente que MAXLEN recortó: redis-py lo entrega con
        # campos vacíos (`{}`), así que falla aquí con KeyError.
        log.error(
            "mensaje_no_procesable", extra={"mensaje_id": mensaje_id, "motivo_error": str(err)}
        )
        return _Destino.CONFIRMADO, False

    with contexto_correlacion(evento.correlation_id):
        try:
            return _evaluar(evento, repositorio, validacion, reloj)
        except Exception:
            # Un fallo inesperado (un bug, no una caída de Validación) no debe
            # detener la auditoría de todos los demás: se registra y se confirma.
            log.exception("evento_fallido", extra={"evento_id": evento.evento_id})
            return _Destino.CONFIRMADO, False


def _procesar_lote(
    cliente: ClienteCola,
    config: Config,
    repositorio: Repositorio,
    validacion: ClienteValidacion,
    reloj: Reloj,
    desde: str,
) -> ResultadoLote:
    try:
        lotes: Any = cliente.xreadgroup(
            groupname=config.grupo,
            consumername=config.consumidor,
            streams={config.stream_auditoria: desde},
            count=config.tamano_lote,
            block=None,
        )
    except ResponseError as err:
        # NOGROUP: alguien vació Redis entre corridas. Se recrea y se sigue.
        if "NOGROUP" not in str(err):
            raise
        log.warning("consumer group desaparecido, recreando", extra={"grupo": config.grupo})
        asegurar_grupo(cliente, config)
        return ResultadoLote()

    mensajes: list[tuple[str, dict[str, str]]] = [
        mensaje for _stream, lote in lotes or [] for mensaje in lote
    ]
    anomalias = 0
    for mensaje_id, campos in mensajes:
        destino, informada = _procesar_mensaje(mensaje_id, campos, repositorio, validacion, reloj)
        if destino is _Destino.PENDIENTE:
            return ResultadoLote(eventos=len(mensajes), anomalias=anomalias, fallo_transitorio=True)
        cliente.xack(config.stream_auditoria, config.grupo, mensaje_id)
        anomalias += informada
    return ResultadoLote(
        eventos=len(mensajes), anomalias=anomalias, lleno=len(mensajes) >= config.tamano_lote
    )


def un_ciclo(
    cliente: ClienteCola,
    config: Config,
    repositorio: Repositorio,
    validacion: ClienteValidacion,
    reloj: Reloj = ahora_utc,
) -> ResultadoCiclo:
    inicio = perf_counter()
    pendientes = _procesar_lote(cliente, config, repositorio, validacion, reloj, desde="0")
    nuevos = (
        ResultadoLote()
        if pendientes.fallo_transitorio
        else _procesar_lote(cliente, config, repositorio, validacion, reloj, desde=">")
    )
    resultado = ResultadoCiclo(
        eventos=pendientes.eventos + nuevos.eventos,
        anomalias=pendientes.anomalias + nuevos.anomalias,
        lleno=pendientes.lleno or nuevos.lleno,
        fallo_transitorio=pendientes.fallo_transitorio or nuevos.fallo_transitorio,
        duracion_ms=round((perf_counter() - inicio) * 1000),
    )
    log.info(
        "ciclo_terminado",
        extra={
            "eventos": resultado.eventos,
            "anomalias": resultado.anomalias,
            "duracion_ms": resultado.duracion_ms,
            "lleno": resultado.lleno,
            "fallo_transitorio": resultado.fallo_transitorio,
        },
    )
    return resultado


def bucle(
    cliente: ClienteCola,
    config: Config,
    repositorio: Repositorio,
    validacion: ClienteValidacion,
    parar: threading.Event,
) -> None:
    """Ciclos hasta que se pida detener el proceso. `parar.wait` hace de
    `sleep` interrumpible: SIGTERM se atiende sin esperar el periodo completo."""
    asegurar_grupo(cliente, config)
    log.info(
        "auditor listo",
        extra={
            "grupo": config.grupo,
            "consumidor": config.consumidor,
            "periodo_s": config.periodo_s,
        },
    )
    while not parar.is_set():
        try:
            resultado = un_ciclo(cliente, config, repositorio, validacion)
        except Exception:
            # Redis caído u otro fallo de infraestructura: el proceso no muere;
            # espera un periodo y vuelve a intentar.
            log.exception("ciclo_fallido")
            parar.wait(config.periodo_s)
            continue
        if not resultado.repetir_sin_dormir:
            parar.wait(config.periodo_s)
    log.info("auditor detenido")
