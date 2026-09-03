"""API Gateway mínimo: valida la identidad de la solicitud y la reenvía."""

import logging
import os
import time
import uuid
from typing import Any

import requests
from flask import Flask, Response, jsonify, request

from api_gateway.structured_logging import configurar_logging, registrar_log

app = Flask(__name__)

QUOTATION_SERVICE_URL = os.getenv(
    "QUOTATION_SERVICE_URL", "http://votacion:8000/v1/cotizaciones"
)
UPSTREAM_TIMEOUT_MS = int(os.getenv("UPSTREAM_TIMEOUT_MS", "1000"))

configurar_logging(os.getenv("LOG_LEVEL", "INFO"))


def _respuesta(cuerpo: Any, estado: int, correlation_id: str) -> Response:
    respuesta = jsonify(cuerpo)
    respuesta.status_code = estado
    respuesta.headers["X-Correlation-Id"] = correlation_id
    return respuesta


@app.post("/v1/cotizaciones")
def cotizar() -> Response:
    """Reenvía una cotización sin conocer cómo la procesa el servicio interno."""
    inicio = time.perf_counter()
    correlation_id = str(uuid.uuid7())
    cuerpo = request.get_json(silent=True)

    if not isinstance(cuerpo, dict):
        return _respuesta({"error": "invalid_json"}, 400, correlation_id)

    request_id = str(cuerpo.get("request_id", "")).strip()
    if not request_id:
        return _respuesta({"error": "request_id_required"}, 400, correlation_id)

    try:
        resultado_servicio = requests.post(
            QUOTATION_SERVICE_URL,
            json=cuerpo,
            headers={
                "X-Correlation-Id": correlation_id,
                "X-Request-Id": request_id,
            },
            timeout=UPSTREAM_TIMEOUT_MS / 1000,
        )
    except requests.Timeout:
        _registrar(
            inicio,
            request_id,
            correlation_id,
            504,
            nivel=logging.WARNING,
            error="upstream_timeout",
        )
        return _respuesta({"error": "upstream_timeout"}, 504, correlation_id)
    except requests.RequestException:
        _registrar(
            inicio,
            request_id,
            correlation_id,
            503,
            nivel=logging.ERROR,
            error="upstream_unavailable",
        )
        return _respuesta({"error": "upstream_unavailable"}, 503, correlation_id)

    try:
        respuesta = resultado_servicio.json()
    except ValueError:
        _registrar(
            inicio,
            request_id,
            correlation_id,
            502,
            nivel=logging.WARNING,
            error="invalid_upstream_response",
        )
        return _respuesta({"error": "invalid_upstream_response"}, 502, correlation_id)

    _registrar(inicio, request_id, correlation_id, resultado_servicio.status_code)
    return _respuesta(respuesta, resultado_servicio.status_code, correlation_id)


def _registrar(
    inicio: float,
    request_id: str,
    correlation_id: str,
    estado: int,
    nivel: int = logging.INFO,
    error: str | None = None,
) -> None:
    registrar_log(
        nivel,
        "cotizacion_enrutada",
        request_id=request_id,
        correlation_id=correlation_id,
        status_code=estado,
        total_time_ms=round((time.perf_counter() - inicio) * 1000, 2),
        error=error,
    )
