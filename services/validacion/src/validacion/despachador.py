"""Publica en `sol:*` y espera la respuesta del worker por `resp:{correlation_id}`.

Solo Validación escribe en `sol:*`; la garantía real la da la red (§1.2), pero
este módulo es el único punto del código que lo hace. El pool de Redis del
`crear_app` debe dimensionarse para los hilos de gunicorn: cada `BLPOP`
retiene una conexión mientras espera.
"""

import json
import logging
from typing import Any

from redis import Redis

from validacion.config import Config
from validacion.contracts import (
    CodigoRespuesta,
    EventoSeguridad,
    Operacion,
    SobreOperacion,
    SobreRespuesta,
)
from validacion.errors import (
    ErrorEstadoInvalido,
    ErrorNoEncontrado,
    ErrorTimeoutOperacion,
    ErrorUpstream,
    ErrorValidacion,
)

log = logging.getLogger(__name__)

CAMPO = "data"


def _stream_operacion(config: Config, operacion: Operacion) -> str:
    return config.stream_cotizador if operacion is Operacion.COTIZAR else config.stream_polizas


def _clave_respuesta(config: Config, correlation_id: str) -> str:
    return f"{config.prefijo_respuestas}:{correlation_id}"


def publicar_operacion(cliente: Redis, config: Config, sobre: SobreOperacion) -> None:
    cliente.xadd(
        name=_stream_operacion(config, sobre.operacion),
        fields={CAMPO: json.dumps(sobre.a_dict(), ensure_ascii=False)},
        maxlen=config.stream_maxlen,
        approximate=True,
    )


def publicar_seguridad(cliente: Redis, config: Config, evento: EventoSeguridad) -> None:
    cliente.xadd(
        name=config.stream_seguridad,
        fields={CAMPO: json.dumps(evento.a_dict(), ensure_ascii=False)},
        maxlen=config.stream_maxlen,
        approximate=True,
    )
    log.warning(
        "incidente_publicado",
        extra={
            "motivo": evento.motivo.value,
            "accion": evento.accion.value,
            "employee_id": evento.employee_id,
            "session_id": evento.session_id,
        },
    )


def despachar(cliente: Redis, config: Config, sobre: SobreOperacion) -> dict[str, Any]:
    """Publica el sobre y espera la respuesta con el presupuesto configurado.

    Publicar y esperar van siempre juntos: cuando la operación puede
    ejecutarse (sin OTP pendiente, ya con el rol correcto), no hay un motivo
    para separarlos en dos pasos.
    """
    publicar_operacion(cliente, config, sobre)
    clave = _clave_respuesta(config, sobre.correlation_id)
    try:
        crudo = cliente.blpop([clave], timeout=config.timeout_respuesta_ms / 1000)
        if crudo is None:
            raise ErrorTimeoutOperacion(
                f"sin respuesta para {sobre.correlation_id} en {config.timeout_respuesta_ms} ms"
            )
        _, carga = crudo
        # `decode_responses=True` ya deja texto en producción; se decodifica
        # aquí solo para que el mismo código sirva con un cliente que no lo
        # tenga activado (p. ej. un doble de pruebas mal configurado).
        texto = carga.decode() if isinstance(carga, bytes) else carga
        return _traducir(_leer_respuesta(texto))
    finally:
        cliente.delete(clave)


def _leer_respuesta(carga: str) -> SobreRespuesta:
    try:
        return SobreRespuesta.desde_dict(json.loads(carga))
    except Exception as err:
        raise ErrorUpstream("el worker respondió una carga ilegible") from err


def _traducir(respuesta: SobreRespuesta) -> dict[str, Any]:
    if respuesta.codigo is CodigoRespuesta.OK:
        return respuesta.resultado or {}
    if respuesta.codigo is CodigoRespuesta.NO_ENCONTRADA:
        raise ErrorNoEncontrado(respuesta.error or "recurso no encontrado")
    if respuesta.codigo is CodigoRespuesta.ESTADO_INVALIDO:
        raise ErrorEstadoInvalido(respuesta.error or "estado inválido para la operación")
    if respuesta.codigo is CodigoRespuesta.VALIDACION:
        raise ErrorValidacion(respuesta.error or "solicitud inválida")
    raise ErrorUpstream(respuesta.error or "el worker falló internamente")
