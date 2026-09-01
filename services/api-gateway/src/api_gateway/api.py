"""Endpoints públicos. El gateway enruta: no calcula, no vota, no persiste."""

import logging
import time
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from api_gateway import cliente_votacion
from api_gateway.config import Config
from api_gateway.limitador import Limitador
from solventa_common.errors import ErrorSocioNoIdentificado
from solventa_common.ids import nuevo_correlation_id
from solventa_common.logging_ import contexto_correlacion, fijar_correlation_id

log = logging.getLogger(__name__)

api = Blueprint("api", __name__)
salud = Blueprint("salud", __name__)


def _config() -> Config:
    config: Config = current_app.config["SOLVENTA"]
    return config


def _limitador() -> Limitador:
    limitador: Limitador = current_app.extensions["limitador"]
    return limitador


def _socio() -> str:
    socio = request.headers.get("X-Partner-Id", "").strip()
    if not socio:
        raise ErrorSocioNoIdentificado("falta la cabecera X-Partner-Id")
    return socio


@api.post("/v1/cotizaciones")
def cotizar() -> tuple[Response, int]:
    config = _config()
    socio = _socio()

    # El correlation_id se genera SIEMPRE aquí: es el único punto por el que
    # entra un journey, y así ningún tramo interno tiene que inventarse uno.
    correlation_id = nuevo_correlation_id()
    entrante = request.headers.get("X-Request-Id", "").strip()
    request_id = entrante or correlation_id
    fijar_correlation_id(correlation_id)

    with contexto_correlacion(correlation_id):
        decision = _limitador().registrar(socio, time.time())
        if not decision.permitido:
            log.warning("socio limitado", extra={"socio": socio})
            return _limitado(decision.reintentar_en, correlation_id)

        try:
            respuesta = cliente_votacion.cotizar(
                config,
                request.get_data(),
                correlation_id=correlation_id,
                request_id=request_id,
            )
        except cliente_votacion.VotacionInalcanzableError as err:
            # No se filtra el motivo real: el socio no debe enterarse de la
            # topología interna ni de qué componente falló.
            log.error("votación inalcanzable", extra={"motivo": str(err), "socio": socio})
            return _problema(
                "https://solventa.co/errors/servicio-no-disponible",
                "El servicio de cotización no está disponible",
                503,
                "vuelva a intentarlo en unos instantes",
                correlation_id,
            )

        cuerpo = _sellar(_depurar(respuesta.cuerpo, config), correlation_id)
        log.info(
            "cotización enrutada",
            extra={"socio": socio, "estado_votacion": respuesta.estado},
        )
        return jsonify(cuerpo), respuesta.estado


def _depurar(cuerpo: dict[str, Any], config: Config) -> dict[str, Any]:
    """Última barrera antes del socio.

    ASR-12 exige responder «sin exponer el error». Aunque Votación incluya el
    bloque `consenso` porque está midiendo el experimento, el gateway lo retira
    si su propia configuración dice que no debe salir. Que la decisión se tome
    dos veces es deliberado: el borde no delega en el interior lo que el socio
    puede ver.
    """
    if config.expose_consensus:
        return cuerpo
    return {clave: valor for clave, valor in cuerpo.items() if clave != "consenso"}


def _sellar(cuerpo: dict[str, Any], correlation_id: str) -> dict[str, Any]:
    """El gateway es la autoridad sobre la identidad del journey.

    Reescribe `correlation_id` e `instance` en lo que devuelve, venga de donde
    venga: un problem+json generado aguas abajo puede traer el suyo o ninguno,
    y el socio solo conoce el que le devolvió el borde.
    """
    if "correlation_id" in cuerpo or "status" in cuerpo:
        cuerpo = cuerpo | {"correlation_id": correlation_id}
    if "instance" in cuerpo:
        cuerpo["instance"] = request.path
    return cuerpo


def _problema(
    tipo: str, titulo: str, estado: int, detalle: str, correlation_id: str
) -> tuple[Response, int]:
    respuesta = jsonify(
        {
            "type": tipo,
            "title": titulo,
            "status": estado,
            "detail": detalle,
            "instance": request.path,
            "correlation_id": correlation_id,
        }
    )
    respuesta.mimetype = "application/problem+json"
    return respuesta, estado


def _limitado(reintentar_en: int, correlation_id: str) -> tuple[Response, int]:
    respuesta, estado = _problema(
        "https://solventa.co/errors/limite-excedido",
        "Se excedió el límite de peticiones",
        429,
        f"reintente en {reintentar_en} s",
        correlation_id,
    )
    respuesta.headers["Retry-After"] = str(reintentar_en)
    return respuesta, estado


@salud.get("/health")
def health() -> tuple[Response, int]:
    return jsonify({"estado": "vivo"}), 200


@salud.get("/ready")
def ready() -> tuple[Response, int]:
    """Readiness: además de vivo, con Votación alcanzable."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{_config().url_votacion}/health", timeout=2) as respuesta:
            aguas_abajo = respuesta.status == 200
    except urllib.error.URLError, TimeoutError, OSError:
        aguas_abajo = False

    return jsonify({"estado": "listo" if aguas_abajo else "no listo", "votacion": aguas_abajo}), (
        200 if aguas_abajo else 503
    )
