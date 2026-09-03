"""App factory.

Nunca un `app = Flask(__name__)` global con rutas colgando debajo: la factory
permite construir la aplicación con una configuración distinta en los tests
—un fichero temporal en vez del volumen— sin tocar variables de entorno del
proceso.
"""

import logging
from typing import Any

from flask import Flask, Response, jsonify, request

from gestion_errores import structured_logging
from gestion_errores.api import api
from gestion_errores.config import Config, desde_entorno
from gestion_errores.errors import ErrorValidacion, a_problem_json
from gestion_errores.repositorio import RepositorioIncidentes
from gestion_errores.structured_logging import correlation_id_actual

log = logging.getLogger(__name__)


def crear_app(config: Config | None = None) -> Flask:
    config = config or desde_entorno()
    structured_logging.configurar("gestion-errores", config.log_level)

    app = Flask(__name__)
    app.config["SOLVENTA"] = config

    repositorio = RepositorioIncidentes(config.ruta_incidentes)
    app.extensions["repositorio"] = repositorio

    app.register_blueprint(api)
    _registrar_errores(app)

    log.info("servicio iniciado", extra={"ruta_incidentes": str(config.ruta_incidentes)})
    return app


def _registrar_errores(app: Flask) -> None:
    """Traducción de excepciones a HTTP en un único sitio."""

    @app.errorhandler(ErrorValidacion)
    def _dominio(err: ErrorValidacion) -> tuple[Response, int]:
        cuerpo, estado = a_problem_json(
            err,
            instance=request.path,
            correlation_id=correlation_id_actual() or "-",
        )
        respuesta = jsonify(cuerpo)
        respuesta.mimetype = "application/problem+json"
        return respuesta, estado

    @app.errorhandler(404)
    def _no_encontrado(_err: Any) -> tuple[Response, int]:
        return jsonify({"title": "Recurso no encontrado", "status": 404}), 404
