"""Endpoints HTTP. Las vistas no tienen lógica: validan, delegan y serializan."""

import logging
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from gestion_errores.escritor import EscritorIncidentes
from gestion_errores.repositorio import RepositorioIncidentes
from solventa_common.contracts import Incidente
from solventa_common.errors import ErrorValidacion
from solventa_common.logging_ import contexto_correlacion

log = logging.getLogger(__name__)

api = Blueprint("api", __name__)
salud = Blueprint("salud", __name__)


def _escritor() -> EscritorIncidentes:
    escritor: EscritorIncidentes = current_app.extensions["escritor"]
    return escritor


def _repositorio() -> RepositorioIncidentes:
    repositorio: RepositorioIncidentes = current_app.extensions["repositorio"]
    return repositorio


@api.post("/v1/incidentes")
def reportar() -> tuple[Response, int]:
    """Acepta un incidente y responde de inmediato.

    202 y no 201: cuando se responde, el incidente está aceptado pero puede no
    estar aún en disco. Decir 201 Created sería mentir sobre una escritura que
    todavía no ha ocurrido.
    """
    cuerpo: Any = request.get_json(silent=True)
    if not isinstance(cuerpo, dict):
        raise ErrorValidacion("cuerpo", "debe ser un objeto JSON")

    incidente = Incidente.desde_dict(cuerpo)

    with contexto_correlacion(incidente.correlation_id):
        _escritor().encolar(incidente.a_dict())
        log.info(
            "incidente aceptado",
            extra={
                "tipo": incidente.tipo.value,
                "replicas_divergentes": list(incidente.replicas_divergentes),
            },
        )

    return jsonify({"aceptado": True, "correlation_id": incidente.correlation_id}), 202


@api.get("/v1/incidentes")
def consultar() -> tuple[Response, int]:
    """Consulta por journey, o el histórico reciente. Lo usan las aserciones de F7."""
    correlation_id = request.args.get("correlation_id")
    if correlation_id:
        incidentes = _repositorio().por_correlation_id(correlation_id)
    else:
        incidentes = _repositorio().todos(limite=request.args.get("limite", 100, type=int))
    return jsonify({"total": len(incidentes), "incidentes": incidentes}), 200


@api.get("/v1/metricas")
def metricas() -> tuple[Response, int]:
    """Numerador de ASR-11.

    `pendientes` es parte de la respuesta a propósito: leer métricas con
    pendientes > 0 contaría de menos, y quien mide necesita saberlo en vez de
    adivinarlo con una espera arbitraria.
    """
    escritor = _escritor()
    cuerpo = _repositorio().metricas().a_dict() | {
        "pendientes_de_escritura": escritor.pendientes,
        "rechazados_por_cola_llena": escritor.perdidos,
    }
    return jsonify(cuerpo), 200


@salud.get("/health")
def health() -> tuple[Response, int]:
    """Liveness: el proceso responde."""
    return jsonify({"estado": "vivo"}), 200


@salud.get("/ready")
def ready() -> tuple[Response, int]:
    """Readiness: además, el hilo escritor vive y el fichero es escribible.

    Un proceso que acepta 202 con el escritor muerto perdería toda la evidencia
    en silencio; eso no es estar listo.
    """
    escritor = _escritor()
    repositorio = _repositorio()
    escribible = repositorio.ruta.exists()
    listo = escritor.esta_vivo() and escribible
    cuerpo = {
        "estado": "listo" if listo else "no listo",
        "escritor_vivo": escritor.esta_vivo(),
        "almacen_escribible": escribible,
    }
    return jsonify(cuerpo), (200 if listo else 503)
