"""App factory de Validación. Arranca también el hilo de Reacción."""

import logging
import uuid
from typing import Any

from flask import Flask, Response, jsonify, request
from redis import Redis

from validacion import reaccion, seed, structured_logging
from validacion.api import api, experimento
from validacion.cliente_autenticacion import ClienteAutenticacion, ClienteAutenticacionHttp
from validacion.config import Config, desde_entorno
from validacion.errors import ErrorSolventa, a_problem_json
from validacion.repositorio import Repositorio
from validacion.structured_logging import correlation_id_actual, fijar_correlation_id

log = logging.getLogger(__name__)

CABECERA_CORRELACION = "X-Correlation-Id"


def crear_app(
    config: Config | None = None,
    repositorio: Repositorio | None = None,
    cliente_redis: Redis | None = None,
    cliente_autenticacion: ClienteAutenticacion | None = None,
) -> Flask:
    config = config or desde_entorno()
    structured_logging.configurar("validacion", config.log_level)

    repositorio = repositorio or Repositorio(config.ruta_db)
    repositorio.inicializar()
    sembradas = seed.sembrar(repositorio)

    if cliente_redis is None:
        # Cada BLPOP retiene una conexión mientras espera una respuesta, y el
        # hilo de Reacción retiene otra en su XREADGROUP: el pool debe dar
        # abasto a todos los hilos de gunicorn más ese, o unas peticiones
        # bloquearían a otras esperando conexión.
        cliente_redis = Redis.from_url(config.redis_url, decode_responses=True, max_connections=64)

    app = Flask(__name__)
    app.config["SOLVENTA"] = config
    app.extensions["repositorio"] = repositorio
    app.extensions["redis"] = cliente_redis

    app.register_blueprint(api)
    if config.modo_experimento:
        # Sin el modo, la ruta no existe: en un despliegue real responde 404.
        app.register_blueprint(experimento)

    _registrar_correlacion(app)
    _registrar_errores(app)

    if config.reaccion_activa:
        # Un solo worker de gunicorn ⇒ un solo consumidor del stream. La
        # reacción sigue siendo asíncrona: la API publica en `seguridad` y
        # este hilo consume, revoca, bloquea y registra la alerta.
        reaccion.iniciar(
            cliente_redis,
            config,
            repositorio,
            cliente_autenticacion or ClienteAutenticacionHttp(config),
        )

    log.info(
        "servicio iniciado",
        extra={
            "modo_experimento": config.modo_experimento,
            "timeout_respuesta_ms": config.timeout_respuesta_ms,
            "reaccion_activa": config.reaccion_activa,
            "autorizaciones_sembradas": sembradas,
        },
    )
    return app


def _registrar_correlacion(app: Flask) -> None:
    @app.before_request
    def _entrada() -> None:
        # El gateway ya fija el identificador del journey; si nadie lo hizo
        # (llamada directa en validación de fase), se genera uno aquí. Las
        # rutas que reciben `correlation_id` en el cuerpo lo vuelven a fijar
        # con ese valor: es el que identifica el journey, no la petición HTTP.
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
