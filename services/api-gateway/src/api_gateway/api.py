"""Rutas HTTP públicas de api-gateway (PLAN-IMPLEMENTACION.md §3.2).

El gateway no interpreta el token, no conoce roles ni alcances y no tiene
lógica de negocio: cada ruta protegida verifica la sesión, arma el `actor` o
el cuerpo que le toca al servicio interno, y propaga estado, cuerpo y
`Content-Type` tal cual.
"""

from collections.abc import Mapping
from typing import Any

from flask import Blueprint, Response, current_app, g, jsonify, request

from api_gateway.config import Config
from api_gateway.contracts import Actor, CuerpoOtp
from api_gateway.errors import ErrorValidacion
from api_gateway.http import ClienteHttp, RespuestaInterna
from api_gateway.sesion import token_desde_cabecera, verificar
from api_gateway.structured_logging import correlation_id_actual

api = Blueprint("api", __name__)


def _config() -> Config:
    config: Config = current_app.config["SOLVENTA"]
    return config


def _cliente() -> ClienteHttp:
    cliente: ClienteHttp = current_app.extensions["http"]
    return cliente


def _cid() -> str:
    return correlation_id_actual() or "-"


def _cuerpo() -> Mapping[str, Any]:
    cuerpo = request.get_json(silent=True)
    if not isinstance(cuerpo, dict):
        raise ErrorValidacion("cuerpo", "debe ser un objeto JSON")
    return cuerpo


def _propagar(respuesta: RespuestaInterna) -> tuple[Response, int]:
    salida = jsonify(respuesta.cuerpo)
    salida.mimetype = respuesta.content_type
    return salida, respuesta.estado


def _autenticar() -> Actor:
    token = token_desde_cabecera(request.headers.get("Authorization"))
    actor = verificar(_cliente(), _config().url_autenticacion, token, _cid())
    g.employee_id = actor.employee_id
    return actor


@api.get("/health")
def health() -> tuple[Response, int]:
    g.operacion = "health"
    return jsonify({"estado": "ok"}), 200


@api.post("/v1/sesiones")
def iniciar_sesion() -> tuple[Response, int]:
    """Reenvía el cuerpo tal cual: validarlo es tarea de Autenticación, no del
    gateway. No requiere Bearer."""
    g.operacion = "login"
    cuerpo = request.get_json(silent=True)
    respuesta = _cliente().post(f"{_config().url_autenticacion}/v1/sesiones", cuerpo, _cid())
    return _propagar(respuesta)


@api.post("/v1/otp")
def resolver_otp() -> tuple[Response, int]:
    g.operacion = "otp"
    actor = _autenticar()
    cuerpo = CuerpoOtp.desde_dict(_cuerpo())
    payload = {"correlation_id": _cid(), "session_id": actor.session_id, "codigo": cuerpo.codigo}
    respuesta = _cliente().post(f"{_config().url_validacion}/v1/otp", payload, _cid())
    return _propagar(respuesta)


def _operar(operacion: str, parametros: Mapping[str, Any]) -> tuple[Response, int]:
    g.operacion = operacion
    actor = _autenticar()
    payload = {
        "correlation_id": _cid(),
        "actor": actor.a_dict(),
        "operacion": operacion,
        "parametros": parametros,
    }
    respuesta = _cliente().post(f"{_config().url_validacion}/v1/operaciones", payload, _cid())
    return _propagar(respuesta)


@api.get("/v1/polizas/<poliza_id>")
def consultar_poliza(poliza_id: str) -> tuple[Response, int]:
    return _operar("consultar_poliza", {"poliza_id": poliza_id})


@api.post("/v1/polizas/<poliza_id>/aprobacion")
def aprobar_poliza(poliza_id: str) -> tuple[Response, int]:
    return _operar("aprobar_poliza", {"poliza_id": poliza_id})


@api.post("/v1/cotizaciones")
def cotizar() -> tuple[Response, int]:
    return _operar("cotizar", _cuerpo())
