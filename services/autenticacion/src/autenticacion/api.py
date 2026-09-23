"""Rutas HTTP de Autenticación (PLAN-IMPLEMENTACION.md §3.3, §5.6)."""

import logging
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from autenticacion import claves, tokens
from autenticacion.config import Config
from autenticacion.contracts import (
    CuerpoCambioRol,
    CuerpoContencion,
    CuerpoLogin,
    CuerpoVerificacion,
    MotivoInvalidez,
    Sesion,
    iso_utc,
)
from autenticacion.errors import (
    ErrorCredenciales,
    ErrorEmpleadoBloqueado,
    ErrorNoEncontrado,
    ErrorValidacion,
)
from autenticacion.repositorio import Repositorio
from autenticacion.structured_logging import correlation_id_actual, fijar_correlation_id

log = logging.getLogger(__name__)

api = Blueprint("api", __name__)
experimento = Blueprint("experimento", __name__)


def _repositorio() -> Repositorio:
    repositorio: Repositorio = current_app.extensions["repositorio"]
    return repositorio


def _config() -> Config:
    config: Config = current_app.config["SOLVENTA"]
    return config


def _ahora() -> datetime:
    reloj: Callable[[], datetime] = current_app.extensions["reloj"]
    return reloj()


def _cuerpo() -> Mapping[str, Any]:
    cuerpo = request.get_json(silent=True)
    if not isinstance(cuerpo, dict):
        raise ErrorValidacion("el cuerpo debe ser un objeto JSON")
    return cuerpo


@api.get("/health")
def health() -> tuple[Response, int]:
    return jsonify({"estado": "ok"}), 200


# --- Login --------------------------------------------------------------------


@api.post("/v1/sesiones")
def iniciar_sesion() -> tuple[Response, int]:
    cuerpo = CuerpoLogin.desde_dict(_cuerpo())
    repositorio = _repositorio()

    empleado = repositorio.empleado_por_usuario(cuerpo.usuario)
    if empleado is None:
        claves.gastar_tiempo_equivalente(cuerpo.password)
        log.info("login_rechazado", extra={"usuario": cuerpo.usuario, "motivo": "CREDENCIALES"})
        raise ErrorCredenciales("usuario o contraseña incorrectos")
    if not claves.verificar(cuerpo.password, empleado.hash_password):
        log.info("login_rechazado", extra={"usuario": cuerpo.usuario, "motivo": "CREDENCIALES"})
        raise ErrorCredenciales("usuario o contraseña incorrectos")
    # Después de la contraseña, no antes: sin ella no se revela que el
    # usuario existe ni que está bloqueado.
    if empleado.bloqueado_en is not None:
        log.info(
            "login_rechazado",
            extra={"employee_id": empleado.employee_id, "motivo": "BLOQUEADO"},
        )
        raise ErrorEmpleadoBloqueado(
            f"{empleado.employee_id} bloqueado desde {iso_utc(empleado.bloqueado_en)}"
            f" por {empleado.motivo_bloqueo}"
        )

    config = _config()
    session_id = str(uuid.uuid7())
    token, claims = tokens.emitir(
        config.jwt_secret,
        config.jwt_ttl_s,
        empleado.employee_id,
        session_id,
        empleado.rol,
        _ahora(),
    )
    repositorio.insertar_sesion(
        Sesion(
            session_id=session_id,
            employee_id=empleado.employee_id,
            rol=empleado.rol,
            emitida_en=claims.emitido_en,
            expira_en=claims.expira_en,
        )
    )
    log.info(
        "sesion_iniciada",
        extra={
            "employee_id": empleado.employee_id,
            "session_id": session_id,
            "rol": empleado.rol.value,
        },
    )
    return (
        jsonify(
            {
                "correlation_id": correlation_id_actual(),
                "session_id": session_id,
                "employee_id": empleado.employee_id,
                "rol": empleado.rol.value,
                "token": token,
                "expira_en": iso_utc(claims.expira_en),
            }
        ),
        201,
    )


# --- Verificación (§5.6) ------------------------------------------------------


@api.post("/v1/sesiones/verificar")
def verificar_sesion() -> tuple[Response, int]:
    """Nunca responde 401: el gateway necesita el `motivo` para elegir el
    `type` correcto. Solo un cuerpo malformado es error (422)."""
    cuerpo = CuerpoVerificacion.desde_dict(_cuerpo())
    resultado = _verificar(cuerpo.token)
    if resultado["valida"]:
        log.debug("sesion_verificada", extra={"session_id": resultado["session_id"]})
    else:
        log.info("sesion_rechazada", extra={k: v for k, v in resultado.items() if k != "valida"})
    return jsonify(resultado), 200


def _invalida(motivo: MotivoInvalidez, **identificacion: str) -> dict[str, Any]:
    return {"valida": False, "motivo": motivo.value, **identificacion}


def _verificar(token: str) -> dict[str, Any]:
    try:
        claims = tokens.verificar(token, _config().jwt_secret, _ahora())
    except tokens.TokenInvalido:
        return _invalida(MotivoInvalidez.INVALIDA)
    except tokens.TokenExpirado as err:
        return _invalida(MotivoInvalidez.EXPIRADA, session_id=err.session_id)

    repositorio = _repositorio()
    sesion = repositorio.sesion(claims.session_id)
    if sesion is None or sesion.employee_id != claims.employee_id:
        # Firma válida pero sin sesión que la respalde: p. ej. un token de una
        # corrida anterior tras `down -v` con el mismo JWT_SECRET.
        return _invalida(MotivoInvalidez.INVALIDA)

    identificacion = {"session_id": claims.session_id, "employee_id": claims.employee_id}
    if sesion.revocada_en is not None:
        return _invalida(MotivoInvalidez.REVOCADA, **identificacion)
    empleado = repositorio.empleado(claims.employee_id)
    if empleado is None:
        return _invalida(MotivoInvalidez.INVALIDA)
    if empleado.bloqueado_en is not None:
        return _invalida(MotivoInvalidez.BLOQUEADO, **identificacion)

    # El rol es el del claim —el que tenía el empleado al iniciar sesión—, no
    # el actual de `empleados`: alterarlo exige un login nuevo (§3.3).
    return {"valida": True, **identificacion, "rol": claims.rol.value}


# --- Contención (la invoca Reacción) ------------------------------------------


@api.post("/v1/sesiones/<session_id>/revocacion")
def revocar_sesion(session_id: str) -> tuple[Response, int]:
    cuerpo = CuerpoContencion.desde_dict(_cuerpo())
    fijar_correlation_id(cuerpo.correlation_id)

    resultado = _repositorio().revocar(session_id, cuerpo.motivo, cuerpo.correlation_id, _ahora())
    if resultado is None:
        raise ErrorNoEncontrado(f"sesión {session_id} inexistente")

    log.info(
        "sesion_ya_revocada" if resultado.ya_estaba_revocada else "sesion_revocada",
        extra={"session_id": session_id, "motivo": cuerpo.motivo, "evento_id": cuerpo.evento_id},
    )
    return (
        jsonify(
            {
                "session_id": resultado.session_id,
                "revocada_en": iso_utc(resultado.revocada_en),
                "ya_estaba_revocada": resultado.ya_estaba_revocada,
            }
        ),
        200,
    )


@api.post("/v1/empleados/<employee_id>/bloqueo")
def bloquear_empleado(employee_id: str) -> tuple[Response, int]:
    cuerpo = CuerpoContencion.desde_dict(_cuerpo())
    fijar_correlation_id(cuerpo.correlation_id)

    resultado = _repositorio().bloquear(employee_id, cuerpo.motivo, _ahora())
    if resultado is None:
        raise ErrorNoEncontrado(f"empleado {employee_id} inexistente")

    log.info(
        "empleado_ya_bloqueado" if resultado.ya_estaba_bloqueado else "empleado_bloqueado",
        extra={
            "employee_id": employee_id,
            "motivo": cuerpo.motivo,
            "evento_id": cuerpo.evento_id,
            "sesiones_afectadas": resultado.sesiones_afectadas,
        },
    )
    return (
        jsonify(
            {
                "employee_id": resultado.employee_id,
                "bloqueado_en": iso_utc(resultado.bloqueado_en),
                "ya_estaba_bloqueado": resultado.ya_estaba_bloqueado,
                "sesiones_afectadas": resultado.sesiones_afectadas,
            }
        ),
        200,
    )


# --- Experimento --------------------------------------------------------------


@experimento.put("/v1/experimento/empleados/<employee_id>/rol")
def alterar_rol(employee_id: str) -> tuple[Response, int]:
    """La alteración del atacante: cambia el rol en `empleados` y nada más.
    Solo existe con MODO_EXPERIMENTO=true."""
    cuerpo = CuerpoCambioRol.desde_dict(_cuerpo())
    anterior = _repositorio().cambiar_rol(employee_id, cuerpo.rol)
    if anterior is None:
        raise ErrorNoEncontrado(f"empleado {employee_id} inexistente")
    log.warning(
        "rol_alterado",
        extra={"employee_id": employee_id, "rol_anterior": anterior.value, "rol": cuerpo.rol.value},
    )
    return (
        jsonify(
            {"employee_id": employee_id, "rol_anterior": anterior.value, "rol": cuerpo.rol.value}
        ),
        200,
    )
