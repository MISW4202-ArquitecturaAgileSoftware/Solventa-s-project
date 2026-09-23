"""Rutas HTTP de Validación (PLAN-IMPLEMENTACION.md §3.4, §5.1-§5.3)."""

import logging
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request
from redis import Redis

from validacion import despachador, otp
from validacion.config import Config
from validacion.contracts import (
    AccionSeguridad,
    CuerpoAnomalia,
    CuerpoOperacion,
    CuerpoOtp,
    EventoSeguridad,
    MotivoSeguridad,
    OtpPendiente,
    SobreOperacion,
    ahora_utc,
    iso_utc,
)
from validacion.errors import (
    ErrorNoEncontrado,
    ErrorOperacionNoAutorizada,
    ErrorOtpFallido,
    ErrorOtpPendiente,
    ErrorSinOtpPendiente,
    ErrorValidacion,
)
from validacion.repositorio import Repositorio
from validacion.structured_logging import fijar_correlation_id

log = logging.getLogger(__name__)

api = Blueprint("api", __name__)
experimento = Blueprint("experimento", __name__)


def _repositorio() -> Repositorio:
    repositorio: Repositorio = current_app.extensions["repositorio"]
    return repositorio


def _redis() -> Redis:
    cliente: Redis = current_app.extensions["redis"]
    return cliente


def _config() -> Config:
    config: Config = current_app.config["SOLVENTA"]
    return config


def _cuerpo() -> Mapping[str, Any]:
    cuerpo = request.get_json(silent=True)
    if not isinstance(cuerpo, dict):
        raise ErrorValidacion("el cuerpo debe ser un objeto JSON")
    return cuerpo


@api.get("/health")
def health() -> tuple[Response, int]:
    return jsonify({"estado": "ok"}), 200


@api.post("/v1/operaciones")
def operaciones() -> tuple[Response, int]:
    cuerpo = CuerpoOperacion.desde_dict(_cuerpo())
    fijar_correlation_id(cuerpo.correlation_id)
    repositorio = _repositorio()

    if not repositorio.operacion_permitida(cuerpo.actor.rol, cuerpo.operacion):
        raise ErrorOperacionNoAutorizada(
            f"el rol {cuerpo.actor.rol.value} no tiene la operación {cuerpo.operacion.value}"
        )
    if repositorio.otp_pendiente(cuerpo.actor.session_id) is not None:
        raise ErrorOtpPendiente(f"ya hay un OTP pendiente para la sesión {cuerpo.actor.session_id}")

    autorizacion = repositorio.autorizacion(cuerpo.actor.employee_id)
    if autorizacion is None:
        raise ErrorOperacionNoAutorizada(f"empleado {cuerpo.actor.employee_id} desconocido")

    ahora = ahora_utc()
    sobre = SobreOperacion.desde_operacion(cuerpo, ahora)

    if autorizacion.ultimo_rol_observado is not cuerpo.actor.rol:
        return _retener_otp(repositorio, autorizacion.canal_otp, cuerpo, sobre, ahora)

    resultado = despachador.despachar(_redis(), _config(), sobre)
    return (
        jsonify({"correlation_id": cuerpo.correlation_id, "estado": "OK", "resultado": resultado}),
        200,
    )


def _retener_otp(
    repositorio: Repositorio,
    canal_otp: str,
    cuerpo: CuerpoOperacion,
    sobre: SobreOperacion,
    ahora: datetime,
) -> tuple[Response, int]:
    pendiente = OtpPendiente(
        session_id=cuerpo.actor.session_id,
        codigo=otp.generar_codigo(),
        correlation_id=cuerpo.correlation_id,
        sobre=sobre,
        creado_en=ahora,
    )
    repositorio.guardar_otp_pendiente(pendiente)
    log.info(
        "otp_emitido",
        extra={
            "employee_id": cuerpo.actor.employee_id,
            "session_id": cuerpo.actor.session_id,
            "canal_otp": canal_otp,
            "operacion": cuerpo.operacion.value,
        },
    )
    detalle = (
        f"primera operación con el rol {cuerpo.actor.rol.value}; enviar el código a POST /v1/otp"
    )
    return (
        jsonify(
            {
                "correlation_id": cuerpo.correlation_id,
                "estado": "OTP_REQUERIDO",
                "session_id": cuerpo.actor.session_id,
                "operacion": cuerpo.operacion.value,
                "detalle": detalle,
            }
        ),
        202,
    )


@api.post("/v1/otp")
def resolver_otp() -> tuple[Response, int]:
    cuerpo = CuerpoOtp.desde_dict(_cuerpo())
    fijar_correlation_id(cuerpo.correlation_id)
    repositorio = _repositorio()

    pendiente = repositorio.otp_pendiente(cuerpo.session_id)
    if pendiente is None:
        raise ErrorSinOtpPendiente(f"no hay OTP pendiente para la sesión {cuerpo.session_id}")

    if not otp.coincide(pendiente.codigo, cuerpo.codigo):
        repositorio.borrar_otp_pendiente(cuerpo.session_id)
        _revocar_por_otp_fallido(cuerpo, pendiente)
        raise ErrorOtpFallido("código incorrecto; la operación fue descartada")

    repositorio.actualizar_rol_observado(
        pendiente.sobre.actor.employee_id, pendiente.sobre.actor.rol, ahora_utc()
    )
    repositorio.borrar_otp_pendiente(cuerpo.session_id)
    resultado = despachador.despachar(_redis(), _config(), pendiente.sobre)
    return (
        jsonify(
            {
                "correlation_id": cuerpo.correlation_id,
                "estado": "OK",
                "operacion": {
                    "correlation_id": pendiente.sobre.correlation_id,
                    "operacion": pendiente.sobre.operacion.value,
                    "resultado": resultado,
                },
            }
        ),
        200,
    )


def _revocar_por_otp_fallido(cuerpo: CuerpoOtp, pendiente: OtpPendiente) -> None:
    evento = EventoSeguridad(
        evento_id=str(uuid.uuid7()),
        correlation_id=cuerpo.correlation_id,
        emitido_en=ahora_utc(),
        employee_id=pendiente.sobre.actor.employee_id,
        session_id=pendiente.session_id,
        motivo=MotivoSeguridad.OTP_FALLIDO,
        accion=AccionSeguridad.REVOCAR,
        detalle={
            "operacion": pendiente.sobre.operacion.value,
            "poliza_id": pendiente.sobre.parametros.get("poliza_id"),
        },
    )
    despachador.publicar_seguridad(_redis(), _config(), evento)


@api.post("/v1/anomalias")
def anomalias() -> tuple[Response, int]:
    cuerpo = CuerpoAnomalia.desde_dict(_cuerpo())
    fijar_correlation_id(cuerpo.correlation_id)
    repositorio = _repositorio()

    autorizacion = repositorio.autorizacion(cuerpo.employee_id)
    if autorizacion is None:
        raise ErrorNoEncontrado(f"empleado {cuerpo.employee_id} desconocido")

    dentro_de_alcance = cuerpo.region_consultada in autorizacion.alcance_autorizado
    motivo = (
        MotivoSeguridad.CONSULTA_INUSUAL
        if dentro_de_alcance
        else MotivoSeguridad.ALCANCE_NO_AUTORIZADO
    )
    accion = AccionSeguridad.ALERTAR if dentro_de_alcance else AccionSeguridad.REVOCAR

    evento = EventoSeguridad(
        evento_id=str(uuid.uuid7()),
        correlation_id=cuerpo.correlation_id,
        emitido_en=ahora_utc(),
        employee_id=cuerpo.employee_id,
        session_id=cuerpo.session_id,
        motivo=motivo,
        accion=accion,
        detalle={
            "accion": cuerpo.accion,
            "region_consultada": cuerpo.region_consultada,
            "alcance_autorizado": autorizacion.alcance_autorizado,
            "evento_auditoria_id": cuerpo.evento_id,
        },
    )
    despachador.publicar_seguridad(_redis(), _config(), evento)
    return jsonify({"evento_id": cuerpo.evento_id, "decision": accion.value}), 202


@api.get("/v1/alertas")
def listar_alertas() -> tuple[Response, int]:
    """Alertas registradas por el proceso de Reacción, en orden de llegada."""
    alertas = [alerta.a_dict() for alerta in _repositorio().listar_alertas()]
    return jsonify({"alertas": alertas, "total": len(alertas)}), 200


@experimento.get("/v1/experimento/otp/<session_id>")
def leer_otp_pendiente(session_id: str) -> tuple[Response, int]:
    """El canal OTP simulado: lo que un canal real (SMS, correo) le mostraría
    al empleado legítimo. Solo en modo experimento."""
    pendiente = _repositorio().otp_pendiente(session_id)
    if pendiente is None:
        raise ErrorSinOtpPendiente(f"no hay OTP pendiente para la sesión {session_id}")
    return (
        jsonify(
            {
                "session_id": pendiente.session_id,
                "codigo": pendiente.codigo,
                "operacion": pendiente.sobre.operacion.value,
                "creado_en": iso_utc(pendiente.creado_en),
            }
        ),
        200,
    )
