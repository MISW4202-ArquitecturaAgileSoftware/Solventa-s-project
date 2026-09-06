"""Fixtures: una app real sobre un fichero temporal, sin tocar el volumen."""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from flask import Flask  # noqa: E402
from flask.testing import FlaskClient  # noqa: E402

from gestion_errores.app import crear_app  # noqa: E402
from gestion_errores.config import Config  # noqa: E402


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        ruta_incidentes=tmp_path / "incidentes.jsonl",
        log_level="WARNING",
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
def incidente() -> dict[str, object]:
    resultado = {
        "moneda": "COP",
        "suma_asegurada": "250000000.00",
        "prima_mensual": "90348.41",
        "prima_anual": "1084180.92",
        "plazo_meses": 240,
        "vigencia_dias": 15,
        "tarifario_version": "2026.02",
        "explicacion": {
            "edad_calculada": 38,
            "tasa_base_mil": "0.26",
            "factores": {
                "fumador": "1.00",
                "clase_ocupacional": "1.12",
                "plazo": "1.08",
                "canal": "0.95",
            },
            "gasto_administrativo": "0.12",
            "margen": "0.08",
        },
    }
    return {
        "correlation_id": "01a05aa8-24a1-753e-b019-a0810d66a3f6",
        "tipo": "divergencia_resultado",
        "detectado_en": "2026-08-31T20:41:07.512Z",
        "replicas_divergentes": ["B"],
        "valores_recibidos": [
            {"cotizador_id": "A", "resultado": resultado, "error": None},
            {
                "cotizador_id": "B",
                "resultado": resultado | {"prima_mensual": "103900.67"},
                "error": None,
            },
            {"cotizador_id": "C", "resultado": resultado, "error": None},
        ],
        "detalle": None,
    }
