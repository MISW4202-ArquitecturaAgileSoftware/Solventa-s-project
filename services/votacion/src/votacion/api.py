"""Endpoints de Votación. La vista valida, delega y serializa; nada más."""

import logging
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request
from redis import Redis

from votacion.common.contracts import (
    EstadoCotizacion,
    Incidente,
    SobreSolicitud,
    SolicitudCotizacion,
    ahora_utc,
    iso_utc,
)
from votacion.common.errors import (
    ErrorSinConsenso,
    ErrorTimeoutCotizacion,
    ErrorValidacion,
)
from votacion.common.ids import es_correlation_id_valido, nuevo_correlation_id
from votacion.common.logging_ import contexto_correlacion, fijar_correlation_id
from votacion import despachador, votador
from votacion.config import Config
from votacion.reportero import Reportero

log = logging.getLogger(__name__)

api = Blueprint("api", __name__)
salud = Blueprint("salud", __name__)


def _config() -> Config:
    config: Config = current_app.config["SOLVENTA"]
    return config


def _redis() -> Redis:
    cliente: Redis = current_app.extensions["redis"]
    return cliente


def _reportero() -> Reportero:
    reportero: Reportero = current_app.extensions["reportero"]
    return reportero


def _correlation_id_entrante() -> str:
    """Adopta el del gateway si viene bien formado; si no, genera uno.

    No se acepta un valor arbitrario del llamante sin validar: acabaría siendo
    parte del nombre de una clave de Redis.
    """
    entrante = request.headers.get("X-Correlation-Id", "")
    if entrante and es_correlation_id_valido(entrante):
        return entrante
    return nuevo_correlation_id()


@api.post("/v1/cotizaciones")
def cotizar() -> tuple[Response, int]:
    config = _config()

    # La correlación se fija ANTES de validar: si se hiciera después, un payload
    # inválido produciría un problem+json sin correlation_id, y justo esas
    # respuestas son las que hay que poder rastrear.
    correlation_id = _correlation_id_entrante()
    fijar_correlation_id(correlation_id)

    cuerpo: Any = request.get_json(silent=True)
    if not isinstance(cuerpo, dict):
        raise ErrorValidacion("cuerpo", "debe ser un objeto JSON")

    solicitud = SolicitudCotizacion.desde_dict(cuerpo)

    with contexto_correlacion(correlation_id):
        # Normalización ANTES del fan-out: la fecha de cálculo y la versión del
        # tarifario se fijan aquí, una sola vez. Si cada réplica las resolviera
        # por su cuenta, una petición en el cambio de día produciría edades
        # distintas y una divergencia falsa.
        emitido_en = ahora_utc()
        sobre = SobreSolicitud(
            correlation_id=correlation_id,
            emitido_en=emitido_en,
            fecha_calculo=emitido_en.date(),
            tarifario_version=config.tarifario_version,
            payload=solicitud,
        )

        cliente = _redis()
        despachador.publicar(cliente, config, sobre)
        recoleccion = despachador.recolectar(cliente, config, correlation_id, solicitud)
        despachador.limpiar(cliente, config, correlation_id)

        veredicto = votador.resolver(
            recoleccion.respuestas,
            solicitud,
            tarifario_esperado=config.tarifario_version,
            quorum=config.quorum,
            replicas_esperadas=config.replicas_esperadas,
        )

        # El reporte se encola ANTES de construir la respuesta pero no se
        # espera: el pool de hilos lo envía mientras el cliente ya está siendo
        # atendido.
        if veredicto.tipo_incidente is not None:
            _reportero().reportar(
                Incidente(
                    correlation_id=correlation_id,
                    tipo=veredicto.tipo_incidente,
                    detectado_en=ahora_utc(),
                    replicas_divergentes=veredicto.replicas_divergentes,
                    valor_consenso=(
                        veredicto.resultado.prima_mensual if veredicto.resultado else None
                    ),
                    valores_recibidos=veredicto.valores_recibidos,
                    detalle=veredicto.detalle,
                )
            )

        log.info(
            "veredicto",
            extra={
                "estado": veredicto.estado.value,
                "respuestas_recibidas": veredicto.respuestas_recibidas,
                "acuerdo": veredicto.acuerdo,
                "replicas_divergentes": list(veredicto.replicas_divergentes),
                "latencia_consenso_ms": recoleccion.latencia_ms,
                "corte": recoleccion.corte.value,
            },
        )

        if veredicto.estado is EstadoCotizacion.RECHAZADO:
            if veredicto.respuestas_recibidas == 0:
                raise ErrorTimeoutCotizacion(
                    f"ninguna réplica respondió en {config.timeout_consenso_ms} ms"
                )
            raise ErrorSinConsenso(veredicto.detalle or "sin coincidencias suficientes")

        assert veredicto.resultado is not None
        return jsonify(
            _respuesta_publica(veredicto, recoleccion, correlation_id, emitido_en, config)
        ), 200


def _respuesta_publica(
    veredicto: votador.Veredicto,
    recoleccion: despachador.Recoleccion,
    correlation_id: str,
    emitido_en: Any,
    config: Config,
) -> dict[str, Any]:
    assert veredicto.resultado is not None
    completo = veredicto.resultado.a_dict()
    explicacion = completo.pop("explicacion")

    cuerpo: dict[str, Any] = {
        "correlation_id": correlation_id,
        "request_id": request.headers.get("X-Request-Id", correlation_id),
        "estado": veredicto.estado.value,
        "emitido_en": iso_utc(emitido_en),
        "cotizacion": completo,
        "explicacion": explicacion,
    }

    # ASR-12 exige responder «sin exponer el error»: en producción el socio
    # nunca ve este bloque. Se activa para poder medir el experimento.
    if config.expose_consensus:
        cuerpo["consenso"] = {
            "estrategia": f"quorum_{config.quorum}_de_{config.replicas_esperadas}",
            "respuestas_recibidas": veredicto.respuestas_recibidas,
            "acuerdo": veredicto.acuerdo,
            "divergencia_detectada": veredicto.hubo_divergencia,
            "replicas_divergentes": list(veredicto.replicas_divergentes),
            "latencia_consenso_ms": recoleccion.latencia_ms,
            "corte": recoleccion.corte.value,
            "detalle": veredicto.detalle,
        }
    return cuerpo


@salud.get("/health")
def health() -> tuple[Response, int]:
    return jsonify({"estado": "vivo"}), 200


@salud.get("/ready")
def ready() -> tuple[Response, int]:
    """Readiness: además de vivo, con la cola alcanzable."""
    try:
        _redis().ping()
        cola = True
    except Exception:
        cola = False
    return jsonify({"estado": "listo" if cola else "no listo", "cola": cola}), (
        200 if cola else 503
    )


@salud.get("/v1/metricas")
def metricas() -> tuple[Response, int]:
    reportero = _reportero()
    return jsonify(
        {
            "incidentes_enviados": reportero.enviados,
            "incidentes_fallidos": reportero.fallidos,
        }
    ), 200
