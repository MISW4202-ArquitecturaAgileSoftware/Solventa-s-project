"""App factory de api-gateway."""

import logging
import time
import uuid
from typing import Any

from flask import Flask, Response, g, jsonify, request

from api_gateway import structured_logging
from api_gateway.api import api
from api_gateway.config import Config, desde_entorno
from api_gateway.errors import ErrorSolventa, a_problem_json
from api_gateway.http import ClienteHttp, ClienteHttpReal
from api_gateway.structured_logging import correlation_id_actual, fijar_correlation_id

log = logging.getLogger(__name__)

CABECERA_CORRELACION = "X-Correlation-Id"


def crear_app(config: Config | None = None, http: ClienteHttp | None = None) -> Flask:
    config = config or desde_entorno()
    structured_logging.configurar("api-gateway", config.log_level)

    app = Flask(__name__)
    app.config["SOLVENTA"] = config
    app.extensions["http"] = http or ClienteHttpReal(config.upstream_timeout_ms / 1000)

    app.register_blueprint(api)

    _registrar_correlacion(app)
    _registrar_errores(app)

    log.info(
        "servicio iniciado",
        extra={
            "url_autenticacion": config.url_autenticacion,
            "url_validacion": config.url_validacion,
            "upstream_timeout_ms": config.upstream_timeout_ms,
        },
    )
    return app


def _registrar_correlacion(app: Flask) -> None:
    @app.before_request
    def _entrada() -> None:
        # api-gateway es el único punto de entrada público: el journey nace
        # aquí, uno por petición (§1.4), sin confiar en un X-Correlation-Id
        # que trajera el cliente.
        fijar_correlation_id(str(uuid.uuid7()))
        g.inicio = time.monotonic()

    @app.after_request
    def _salida(respuesta: Response) -> Response:
        respuesta.headers[CABECERA_CORRELACION] = correlation_id_actual() or "-"
        total_ms = (time.monotonic() - g.get("inicio", time.monotonic())) * 1000
        extra: dict[str, Any] = {
            "ruta": request.path,
            "metodo": request.method,
            "operacion": g.get("operacion"),
            "estado": respuesta.status_code,
            "total_ms": round(total_ms, 1),
        }
        employee_id = g.get("employee_id")
        if employee_id is not None:
            extra["employee_id"] = employee_id
        log.info("peticion_enrutada", extra=extra)
        return respuesta


def _registrar_errores(app: Flask) -> None:
    @app.errorhandler(ErrorSolventa)
    def _dominio(err: ErrorSolventa) -> tuple[Response, int]:
        cuerpo, estado = a_problem_json(
            err, instance=request.path, correlation_id=correlation_id_actual() or "-"
        )
        respuesta = jsonify(cuerpo)
        respuesta.mimetype = "application/problem+json"
        return respuesta, estado

    @app.errorhandler(404)
    def _no_encontrado(_err: Any) -> tuple[Response, int]:
        return jsonify({"title": "Recurso no encontrado", "status": 404}), 404
