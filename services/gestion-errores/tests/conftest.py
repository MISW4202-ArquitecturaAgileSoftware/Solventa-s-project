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
        capacidad_cola=100,
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
def esperar_escritura(app: Flask):  # type: ignore[no-untyped-def]
    """Bloquea hasta que el escritor vació la cola.

    Los tests necesitan determinismo; el servicio, no. Esta espera existe solo
    aquí: en producción quien reporta jamás espera a la escritura.
    """
    import time

    def _esperar(timeout: float = 2.0) -> None:
        escritor = app.extensions["escritor"]
        limite = time.perf_counter() + timeout
        while escritor.pendientes > 0 and time.perf_counter() < limite:
            time.sleep(0.005)
        # El hilo puede haber sacado el elemento de la cola pero no haberlo
        # escrito aún: un respiro corto cierra esa ventana.
        time.sleep(0.02)

    return _esperar


@pytest.fixture
def incidente() -> dict[str, object]:
    return {
        "correlation_id": "01a05aa8-24a1-753e-b019-a0810d66a3f6",
        "tipo": "divergencia_resultado",
        "detectado_en": "2026-08-31T20:41:07.512Z",
        "replicas_divergentes": ["B"],
        "valor_consenso": "90348.41",
        "valores_recibidos": [
            {"cotizador_id": "A", "prima_mensual": "90348.41", "resultado_hash": "9f2a"},
            {"cotizador_id": "B", "prima_mensual": "103900.67", "resultado_hash": "c41d"},
            {"cotizador_id": "C", "prima_mensual": "90348.41", "resultado_hash": "9f2a"},
        ],
        "detalle": None,
    }
