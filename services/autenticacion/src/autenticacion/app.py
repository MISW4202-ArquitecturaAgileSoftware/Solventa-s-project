"""App factory de Autenticación."""

import logging
import uuid
from typing import Any

from flask import Flask, Response, jsonify, request

from autenticacion import seed, structured_logging
from autenticacion.api import api, experimento
from autenticacion.config import Config, desde_entorno
from autenticacion.errors import ErrorSolventa, a_problem_json
from autenticacion.repositorio import Repositorio
from autenticacion.sesiones import ServicioSesiones
from autenticacion.structured_logging import correlation_id_actual, fijar_correlation_id

log = logging.getLogger(__name__)

CABECERA_CORRELACION = "X-Correlation-Id"


def crear_app(config: Config | None = None, repositorio: Repositorio | None = None) -> Flask:
    config = config or desde_entorno()
    structured_logging.configurar("autenticacion", config.log_level)

    repositorio = repositorio or Repositorio(config.ruta_db)
    repositorio.inicializar()
    sembrados = seed.sembrar(repositorio)

    app = Flask(__name__)
    app.config["SOLVENTA"] = config
    app.extensions["sesiones"] = ServicioSesiones(repositorio, config)

    app.register_blueprint(api)
    if config.modo_experimento:
        # Sin el modo, la ruta no existe: en un despliegue real responde 404.
        app.register_blueprint(experimento)

    _registrar_correlacion(app)
    _registrar_errores(app)

    log.info(
        "servicio iniciado",
        extra={
            "modo_experimento": config.modo_experimento,
            "jwt_ttl_s": config.jwt_ttl_s,
            "empleados_sembrados": sembrados,
        },
    )
    return app


def _registrar_correlacion(app: Flask) -> None:
    @app.before_request
    def _entrada() -> None:
        # El gateway ya fija el identificador del journey; si nadie lo hizo
        # (llamada directa en validación de fase), se genera uno aquí.
        fijar_correlation_id(request.headers.get(CABECERA_CORRELACION) or str(uuid.uuid7()))

    @app.after_request
    def _salida(respuesta: Response) -> Response:
        respuesta.headers[CABECERA_CORRELACION] = correlation_id_actual() or "-"
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
