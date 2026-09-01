"""Fixtures del gateway: app real con Votación simulada."""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from flask import Flask  # noqa: E402
from flask.testing import FlaskClient  # noqa: E402

from api_gateway.app import crear_app  # noqa: E402
from api_gateway.config import Config  # noqa: E402


@pytest.fixture
def config() -> Config:
    return Config(
        url_votacion="http://votacion:8000",
        log_level="WARNING",
        timeout_votacion_s=0.3,
        expose_consensus=False,
        limite_por_minuto=5,
    )


@pytest.fixture
def app(config: Config) -> Flask:
    aplicacion = crear_app(config)
    aplicacion.config["TESTING"] = True
    return aplicacion


@pytest.fixture
def cliente(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def solicitud() -> dict[str, object]:
    return {
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


@pytest.fixture
def respuesta_cotizada() -> dict[str, object]:
    """Lo que devolvería Votación, con el bloque `consenso` incluido."""
    return {
        "correlation_id": "01a05aa8-24a1-753e-b019-a0810d66a3f6",
        "request_id": "01a05aa8-24a1-753e-b019-a0810d66a3f6",
        "estado": "COTIZADO",
        "emitido_en": "2026-08-31T20:41:07.512Z",
        "cotizacion": {"prima_mensual": "90348.41", "prima_anual": "1084180.92"},
        "explicacion": {"edad_calculada": 38},
        "consenso": {
            "estrategia": "quorum_2_de_3",
            "respuestas_recibidas": 3,
            "acuerdo": 2,
            "divergencia_detectada": True,
            "replicas_divergentes": ["B"],
            "latencia_consenso_ms": 3,
        },
    }
