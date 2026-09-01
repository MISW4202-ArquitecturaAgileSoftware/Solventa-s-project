"""App factory de Votación."""

import atexit
import logging
from typing import Any

from flask import Flask, Response, jsonify, request
from redis import Redis

from solventa_common import logging_
from solventa_common.errors import ErrorSolventa, a_problem_json
from solventa_common.logging_ import correlation_id_actual
from votacion.api import api, salud
from votacion.config import Config, desde_entorno
from votacion.reportero import Reportero

log = logging.getLogger(__name__)


def crear_app(config: Config | None = None, cliente: Redis | None = None) -> Flask:
    config = config or desde_entorno()
    logging_.configurar("votacion", config.log_level)

    app = Flask(__name__)
    app.config["SOLVENTA"] = config

    if cliente is None:
        # Cada BLPOP retiene una conexión mientras espera, así que el pool debe
        # dar abasto a todos los hilos de gunicorn a la vez o unas peticiones
        # bloquearían a otras esperando conexión.
        cliente = Redis.from_url(
            config.redis_url,
            decode_responses=True,
            max_connections=64,
        )

    reportero = Reportero(config)
    app.extensions["redis"] = cliente
    app.extensions["reportero"] = reportero
    atexit.register(reportero.detener)

    app.register_blueprint(api)
    app.register_blueprint(salud)
    _registrar_errores(app)

    log.info(
        "servicio iniciado",
        extra={
            "quorum": config.quorum,
            "replicas_esperadas": config.replicas_esperadas,
            "timeout_consenso_ms": config.timeout_consenso_ms,
            "gracia_tras_quorum_ms": config.gracia_tras_quorum_ms,
        },
    )
    return app


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
