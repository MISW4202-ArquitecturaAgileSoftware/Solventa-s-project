"""Rutas HTTP de Autenticación (PLAN-IMPLEMENTACION.md §3.3)."""

from collections.abc import Mapping
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from autenticacion.contracts import (
    CuerpoContencion,
    CuerpoLogin,
    CuerpoRol,
    CuerpoToken,
    iso_utc,
)
from autenticacion.errors import ErrorValidacion
from autenticacion.sesiones import ServicioSesiones
from autenticacion.structured_logging import correlation_id_actual

api = Blueprint("api", __name__)
experimento = Blueprint("experimento", __name__)


def _servicio() -> ServicioSesiones:
    servicio: ServicioSesiones = current_app.extensions["sesiones"]
    return servicio


def _cuerpo() -> Mapping[str, Any]:
    cuerpo = request.get_json(silent=True)
    if not isinstance(cuerpo, dict):
        raise ErrorValidacion("cuerpo", "debe ser un objeto JSON")
    return cuerpo


def _respuesta(datos: dict[str, Any], estado: int = 200) -> tuple[Response, int]:
    return jsonify({"correlation_id": correlation_id_actual(), **datos}), estado


@api.get("/health")
def health() -> tuple[Response, int]:
    return jsonify({"estado": "ok"}), 200


@api.post("/v1/sesiones")
def iniciar_sesion() -> tuple[Response, int]:
    cuerpo = CuerpoLogin.desde_dict(_cuerpo())
    sesion = _servicio().iniciar(cuerpo.usuario, cuerpo.password)
    return _respuesta(sesion.a_dict(), 201)


@api.post("/v1/sesiones/verificar")
def verificar_sesion() -> tuple[Response, int]:
    cuerpo = CuerpoToken.desde_dict(_cuerpo())
    return _respuesta(_servicio().verificar(cuerpo.token).a_dict())


@api.post("/v1/sesiones/<session_id>/revocacion")
def revocar_sesion(session_id: str) -> tuple[Response, int]:
    cuerpo = CuerpoContencion.desde_dict(_cuerpo())
    resultado = _servicio().revocar(session_id, cuerpo.motivo, cuerpo.correlation_id)
    return _respuesta(
        {
            "session_id": resultado.session_id,
            "revocada_en": iso_utc(resultado.revocada_en),
            "ya_estaba_revocada": resultado.ya_estaba_revocada,
        }
    )


@api.post("/v1/empleados/<employee_id>/bloqueo")
def bloquear_empleado(employee_id: str) -> tuple[Response, int]:
    cuerpo = CuerpoContencion.desde_dict(_cuerpo())
    resultado = _servicio().bloquear(employee_id, cuerpo.motivo)
    return _respuesta(
        {
            "employee_id": resultado.employee_id,
            "bloqueado_en": iso_utc(resultado.bloqueado_en),
            "ya_estaba_bloqueado": resultado.ya_estaba_bloqueado,
            "sesiones_afectadas": resultado.sesiones_afectadas,
        }
    )


@experimento.put("/v1/experimento/empleados/<employee_id>/rol")
def alterar_rol(employee_id: str) -> tuple[Response, int]:
    """Simula al atacante que altera el rol en la base. Solo en modo experimento."""
    cuerpo = CuerpoRol.desde_dict(_cuerpo())
    cambio = _servicio().alterar_rol(employee_id, cuerpo.rol)
    return _respuesta(
        {
            "employee_id": cambio.employee_id,
            "rol_anterior": cambio.rol_anterior.value,
            "rol": cambio.rol.value,
        }
    )
