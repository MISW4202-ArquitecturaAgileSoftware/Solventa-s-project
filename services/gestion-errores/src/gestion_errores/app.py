"""App factory.

Nunca un `app = Flask(__name__)` global con rutas colgando debajo: la factory
permite construir la aplicación con una configuración distinta en los tests
—un fichero temporal en vez del volumen— sin tocar variables de entorno del
proceso.
"""

import atexit
import logging
from typing import Any

from flask import Flask, Response, jsonify, request

from gestion_errores.api import api, salud
from gestion_errores.config import Config, desde_entorno
from gestion_errores.escritor import ColaLlenaError, EscritorIncidentes
from gestion_errores.repositorio import RepositorioIncidentes
from solventa_common import logging_
from solventa_common.errors import ErrorSolventa, a_problem_json
from solventa_common.logging_ import correlation_id_actual

log = logging.getLogger(__name__)


def crear_app(config: Config | None = None) -> Flask:
    config = config or desde_entorno()
    logging_.configurar("gestion-errores", config.log_level)

    app = Flask(__name__)
    app.config["SOLVENTA"] = config

    repositorio = RepositorioIncidentes(config.ruta_incidentes)
    escritor = EscritorIncidentes(repositorio, config.capacidad_cola)
    escritor.iniciar()

    app.extensions["repositorio"] = repositorio
    app.extensions["escritor"] = escritor

    # Vaciar lo pendiente al apagar: sin esto, los incidentes aceptados y aún
    # no escritos se perderían en cada despliegue.
    atexit.register(escritor.detener)

    app.register_blueprint(api)
    app.register_blueprint(salud)
    _registrar_errores(app)

    log.info("servicio iniciado", extra={"ruta_incidentes": str(config.ruta_incidentes)})
    return app


def _registrar_errores(app: Flask) -> None:
    """Traducción de excepciones a HTTP en un único sitio."""

    @app.errorhandler(ErrorSolventa)
    def _dominio(err: ErrorSolventa) -> tuple[Response, int]:
        cuerpo, estado = a_problem_json(
            err,
            instance=request.path,
            correlation_id=correlation_id_actual() or "-",
            titulo="Incidente inválido" if err.estado == 422 else None,
        )
        respuesta = jsonify(cuerpo)
        respuesta.mimetype = "application/problem+json"
        return respuesta, estado

    @app.errorhandler(ColaLlenaError)
    def _saturado(err: ColaLlenaError) -> tuple[Response, int]:
        # 503 y no 500: el servicio está sano, solo saturado. Quien reporta
        # puede reintentar, aunque Votación nunca debe hacerlo en línea.
        log.error("cola de incidentes saturada")
        respuesta = jsonify(
            {
                "type": "https://solventa.co/errors/registro-saturado",
                "title": "El registro de incidentes está saturado",
                "status": 503,
                "detail": str(err),
                "instance": request.path,
            }
        )
        respuesta.mimetype = "application/problem+json"
        return respuesta, 503

    @app.errorhandler(404)
    def _no_encontrado(_err: Any) -> tuple[Response, int]:
        return jsonify({"title": "Recurso no encontrado", "status": 404}), 404
