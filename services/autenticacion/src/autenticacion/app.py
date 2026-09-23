"""App factory de Autenticación."""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from autenticacion import seed, structured_logging
from autenticacion.api import api, experimento
from autenticacion.config import Config, desde_entorno
from autenticacion.contracts import ahora_utc
from autenticacion.errors import ErrorSolventa, a_problem_json, problem_json_http
from autenticacion.repositorio import Repositorio
from autenticacion.structured_logging import correlation_id_actual, fijar_correlation_id

log = logging.getLogger(__name__)

CABECERA_CORRELACION = "X-Correlation-Id"


def crear_app(
    config: Config | None = None,
    repositorio: Repositorio | None = None,
    reloj: Callable[[], datetime] = ahora_utc,
) -> Flask:
    config = config or desde_entorno()
    structured_logging.configurar("autenticacion", config.log_level)

    repositorio = repositorio or Repositorio(config.ruta_db)
    repositorio.inicializar()
    sembrados = seed.sembrar(repositorio)

    app = Flask(__name__)
    app.config["SOLVENTA"] = config
    app.extensions["repositorio"] = repositorio
    # Inyectable para probar la expiración sin esperar a que pase el tiempo.
    app.extensions["reloj"] = reloj

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
        # El gateway fija el identificador del journey; si nadie lo hizo
        # (llamada directa en validación de fase), se genera uno aquí. Las
        # rutas de contención lo vuelven a fijar con el `correlation_id` del
        # cuerpo, que es el del evento de seguridad que las originó.
        fijar_correlation_id(request.headers.get(CABECERA_CORRELACION) or str(uuid.uuid7()))

    @app.after_request
    def _salida(respuesta: Response) -> Response:
        respuesta.headers[CABECERA_CORRELACION] = correlation_id_actual() or "-"
        return respuesta


def _problem(cuerpo: dict[str, object], estado: int) -> tuple[Response, int]:
    respuesta = jsonify(cuerpo)
    respuesta.mimetype = "application/problem+json"
    return respuesta, estado


def _registrar_errores(app: Flask) -> None:
    @app.errorhandler(ErrorSolventa)
    def _dominio(err: ErrorSolventa) -> tuple[Response, int]:
        cuerpo, estado = a_problem_json(
            err, instance=request.path, correlation_id=correlation_id_actual() or "-"
        )
        return _problem(cuerpo, estado)

    @app.errorhandler(HTTPException)
    def _http(err: HTTPException) -> tuple[Response, int]:
        estado = err.code or 500
        return _problem(
            problem_json_http(
                estado,
                err.name,
                err.description or err.name,
                request.path,
                correlation_id_actual() or "-",
            ),
            estado,
        )

    @app.errorhandler(Exception)
    def _no_previsto(err: Exception) -> tuple[Response, int]:
        log.exception("error_no_previsto")
        return _problem(
            problem_json_http(
                500,
                "Internal Server Error",
                "error interno no previsto",
                request.path,
                correlation_id_actual() or "-",
            ),
            500,
        )
