"""App factory del gateway."""

import logging
from typing import Any

from flask import Flask, Response, jsonify, request

from api_gateway.api import api, salud
from api_gateway.config import Config, desde_entorno
from api_gateway.limitador import Limitador
from solventa_common import logging_
from solventa_common.errors import ErrorSolventa, a_problem_json
from solventa_common.ids import nuevo_correlation_id
from solventa_common.logging_ import correlation_id_actual, fijar_correlation_id

log = logging.getLogger(__name__)

CABECERA_CORRELACION = "X-Correlation-Id"


def crear_app(config: Config | None = None) -> Flask:
    config = config or desde_entorno()
    logging_.configurar("api-gateway", config.log_level)

    app = Flask(__name__)
    app.config["SOLVENTA"] = config
    app.extensions["limitador"] = Limitador(config.limite_por_minuto)

    app.register_blueprint(api)
    app.register_blueprint(salud)
    _registrar_correlacion(app)
    _registrar_errores(app)

    log.info(
        "servicio iniciado",
        extra={
            "url_votacion": config.url_votacion,
            "expose_consensus": config.expose_consensus,
            "limite_por_minuto": config.limite_por_minuto,
        },
    )
    return app


def _registrar_correlacion(app: Flask) -> None:
    """Garantiza que TODA respuesta lleve X-Correlation-Id, errores incluidos.

    Se hace en un `after_request` y no en cada vista porque una respuesta de
    error nace en un manejador que no pasó por la vista; si dependiera de la
    vista, justo las respuestas que más falta hacen rastrear saldrían sin
    identificador.
    """

    @app.before_request
    def _asegurar_correlacion() -> None:
        if correlation_id_actual() is None:
            fijar_correlation_id(nuevo_correlation_id())

    @app.after_request
    def _sellar(respuesta: Response) -> Response:
        respuesta.headers[CABECERA_CORRELACION] = correlation_id_actual() or "-"
        return respuesta

    @app.teardown_request
    def _limpiar(_err: BaseException | None) -> None:
        # El hilo de gunicorn se reutiliza: sin esto, una petición heredaría el
        # identificador de la anterior.
        fijar_correlation_id(None)


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

    @app.errorhandler(405)
    def _metodo(_err: Any) -> tuple[Response, int]:
        return jsonify({"title": "Método no permitido", "status": 405}), 405
