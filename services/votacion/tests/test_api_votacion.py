"""Contrato HTTP de Votación con Redis y la decisión sustituidos por dobles."""

from typing import Any

import pytest

from votacion import api as api_modulo
from votacion.app import crear_app
from votacion.contracts import (
    EstadoCotizacion,
    Incidente,
    ResultadoCotizacion,
    SolicitudCotizacion,
    TipoIncidente,
)
from votacion.config import Config
from votacion.despachador import Corte, Recoleccion
from votacion.votador import Veredicto


class ReporteroDoble:
    def __init__(self) -> None:
        self.incidentes: list[Incidente] = []

    def reportar(self, incidente: Incidente) -> None:
        self.incidentes.append(incidente)

    def detener(self) -> None:
        pass


@pytest.fixture
def config() -> Config:
    return Config(
        redis_url="redis://x",
        stream_solicitudes="cot:req",
        prefijo_respuestas="cot:resp",
        log_level="WARNING",
        replicas_esperadas=3,
        quorum=2,
        timeout_consenso_ms=250,
        gracia_tras_quorum_ms=25,
        stream_maxlen=10000,
        expose_consensus=True,
        url_gestion_errores="http://ge:8000",
        timeout_reporte_s=2.0,
        hilos_reporte=2,
    )


@pytest.fixture
def solicitud_json() -> dict[str, Any]:
    return {
        "request_id": "solicitud-001",
        "producto": "vida_hipotecario",
        "moneda": "COP",
        "suma_asegurada": "250000000.00",
        "plazo_meses": 240,
        "canal": "banco_aliado",
        "asegurado": {
            "fecha_nacimiento": "1988-04-17",
            "genero": "F",
            "fumador": False,
            "clase_ocupacional": 2,
        },
        "consentimiento_open_finance": True,
    }


def _veredicto(resultado: ResultadoCotizacion) -> Veredicto:
    return Veredicto(
        estado=EstadoCotizacion.COTIZADO,
        resultado=resultado,
        respuestas_recibidas=3,
        acuerdo=3,
        replicas_divergentes=(),
        tipo_incidente=None,
        detalle=None,
        valores_recibidos=(),
    )


@pytest.fixture
def servicio(
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    sano: ResultadoCotizacion,
) -> tuple[Any, ReporteroDoble]:
    reportero = ReporteroDoble()
    monkeypatch.setattr(api_modulo.despachador, "publicar", lambda *_a: None)
    monkeypatch.setattr(api_modulo.despachador, "limpiar", lambda *_a: None)
    monkeypatch.setattr(
        api_modulo.despachador,
        "recolectar",
        lambda *_a: Recoleccion([], 2, Corte.COMPLETA),
    )
    monkeypatch.setattr(api_modulo.votador, "resolver", lambda *_a, **_k: _veredicto(sano))
    app = crear_app(config, cliente=object(), reportero=reportero)  # type: ignore[arg-type]
    app.config["TESTING"] = True
    return app.test_client(), reportero


def test_responde_el_resultado_y_conserva_los_identificadores(
    servicio: tuple[Any, ReporteroDoble], solicitud_json: dict[str, Any]
) -> None:
    cliente, _ = servicio
    respuesta = cliente.post(
        "/v1/cotizaciones",
        json=solicitud_json,
        headers={
            "X-Correlation-Id": "01a05aa8-24a1-753e-b019-a0810d66a3f6",
            "X-Request-Id": "solicitud-001",
        },
    )

    cuerpo = respuesta.get_json()
    assert respuesta.status_code == 200
    assert cuerpo["request_id"] == "solicitud-001"
    assert cuerpo["cotizacion"]["prima_mensual"] == "90348.41"
    assert cuerpo["consenso"]["acuerdo"] == 3


def test_rechaza_un_cuerpo_que_no_es_json(servicio: tuple[Any, ReporteroDoble]) -> None:
    cliente, _ = servicio
    respuesta = cliente.post("/v1/cotizaciones", data="no-json")

    assert respuesta.status_code == 422
    assert respuesta.mimetype == "application/problem+json"


def test_reporta_una_divergencia(
    monkeypatch: pytest.MonkeyPatch,
    servicio: tuple[Any, ReporteroDoble],
    solicitud_json: dict[str, Any],
    sano: ResultadoCotizacion,
) -> None:
    cliente, reportero = servicio
    divergente = Veredicto(
        estado=EstadoCotizacion.COTIZADO,
        resultado=sano,
        respuestas_recibidas=3,
        acuerdo=2,
        replicas_divergentes=("B",),
        tipo_incidente=TipoIncidente.DIVERGENCIA_RESULTADO,
        detalle=None,
        valores_recibidos=(),
    )
    monkeypatch.setattr(api_modulo.votador, "resolver", lambda *_a, **_k: divergente)

    respuesta = cliente.post("/v1/cotizaciones", json=solicitud_json)

    assert respuesta.status_code == 200
    assert len(reportero.incidentes) == 1
    assert reportero.incidentes[0].replicas_divergentes == ("B",)


def test_sin_mayoria_responde_503(
    monkeypatch: pytest.MonkeyPatch,
    servicio: tuple[Any, ReporteroDoble],
    solicitud_json: dict[str, Any],
) -> None:
    cliente, _ = servicio
    sin_mayoria = Veredicto(
        estado=EstadoCotizacion.RECHAZADO,
        resultado=None,
        respuestas_recibidas=1,
        acuerdo=1,
        replicas_divergentes=(),
        tipo_incidente=TipoIncidente.SIN_QUORUM,
        detalle="una respuesta no alcanza el quórum",
        valores_recibidos=(),
    )
    monkeypatch.setattr(api_modulo.votador, "resolver", lambda *_a, **_k: sin_mayoria)

    respuesta = cliente.post("/v1/cotizaciones", json=solicitud_json)

    assert respuesta.status_code == 503
    assert respuesta.mimetype == "application/problem+json"
    assert respuesta.get_json()["type"].endswith("/sin-consenso")


def test_sin_respuestas_responde_504(
    monkeypatch: pytest.MonkeyPatch,
    servicio: tuple[Any, ReporteroDoble],
    solicitud_json: dict[str, Any],
) -> None:
    cliente, _ = servicio
    timeout = Veredicto(
        estado=EstadoCotizacion.RECHAZADO,
        resultado=None,
        respuestas_recibidas=0,
        acuerdo=0,
        replicas_divergentes=(),
        tipo_incidente=TipoIncidente.REPLICA_NO_RESPONDE,
        detalle="ninguna réplica respondió",
        valores_recibidos=(),
    )
    monkeypatch.setattr(api_modulo.votador, "resolver", lambda *_a, **_k: timeout)

    respuesta = cliente.post("/v1/cotizaciones", json=solicitud_json)

    assert respuesta.status_code == 504
    assert respuesta.mimetype == "application/problem+json"
    assert respuesta.get_json()["type"].endswith("/timeout-cotizacion")
