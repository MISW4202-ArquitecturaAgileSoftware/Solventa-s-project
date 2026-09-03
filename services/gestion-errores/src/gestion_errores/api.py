"""Endpoints HTTP. Las vistas no tienen lógica: validan, delegan y serializan."""

import logging
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, render_template, request

from gestion_errores import reporte
from gestion_errores.contracts import Incidente
from gestion_errores.errors import ErrorValidacion
from gestion_errores.repositorio import RepositorioIncidentes
from gestion_errores.structured_logging import contexto_correlacion

log = logging.getLogger(__name__)

api = Blueprint("api", __name__)


def _repositorio() -> RepositorioIncidentes:
    repositorio: RepositorioIncidentes = current_app.extensions["repositorio"]
    return repositorio


def _seleccion() -> tuple[list[dict[str, Any]], str | None]:
    """Incidentes que piden los parámetros de la petición: un journey, o los últimos N."""
    correlation_id = request.args.get("correlation_id")
    if correlation_id:
        return _repositorio().por_correlation_id(correlation_id), correlation_id
    limite = request.args.get("limite", 100, type=int)
    return _repositorio().todos(limite=limite), None


@api.post("/v1/incidentes")
def reportar() -> tuple[Response, int]:
    """Valida y persiste el incidente antes de confirmar su creación."""
    cuerpo: Any = request.get_json(silent=True)
    if not isinstance(cuerpo, dict):
        raise ErrorValidacion("cuerpo", "debe ser un objeto JSON")

    incidente = Incidente.desde_dict(cuerpo)

    with contexto_correlacion(incidente.correlation_id):
        _repositorio().anexar(incidente.a_dict())
        log.info(
            "incidente aceptado",
            extra={
                "tipo": incidente.tipo.value,
                "replicas_divergentes": list(incidente.replicas_divergentes),
            },
        )

    return jsonify({"creado": True, "correlation_id": incidente.correlation_id}), 201


@api.get("/v1/incidentes")
def consultar() -> tuple[Response, int]:
    """Consulta por journey, o el histórico reciente. Lo usan las aserciones de F7."""
    incidentes, _ = _seleccion()
    return jsonify({"total": len(incidentes), "incidentes": incidentes}), 200


@api.get("/v1/incidentes/reporte")
def reporte_html() -> tuple[str, int]:
    """El mismo histórico que `GET /v1/incidentes`, como reporte HTML para personas.

    Cada registro responde qué se detectó, cuándo y cómo (qué devolvió cada
    réplica y en qué difieren). Acepta los mismos filtros que el JSON.
    """
    incidentes, correlation_id = _seleccion()
    modelo = reporte.construir(incidentes, filtro_correlation_id=correlation_id)
    return render_template("reporte.html", reporte=modelo), 200


@api.get("/v1/metricas")
def metricas() -> tuple[Response, int]:
    """Numerador de ASR-11, calculado sobre la evidencia ya persistida."""
    return jsonify(_repositorio().metricas().a_dict()), 200
