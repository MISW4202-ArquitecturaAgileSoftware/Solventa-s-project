"""Helpers y dobles de prueba con nombre único en el monorepo.

No viven en `conftest.py` porque cada servicio tiene el suyo y, al correr mypy
desde la raíz, todos resolverían al mismo módulo `conftest`.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flask.testing import FlaskClient

from autenticacion.config import Config

SECRETO = "secreto-de-pruebas-con-al-menos-32-bytes"
TTL_S = 3600
#: Instante fijo de arranque del reloj falso: los tests no dependen de la hora real.
INICIO = datetime(2026, 9, 21, 14, 0, 0, tzinfo=UTC)


def configuracion(tmp_path: Path, **cambios: object) -> Config:
    base: dict[str, object] = {
        "ruta_db": tmp_path / "autenticacion.db",
        "jwt_secret": SECRETO,
        "jwt_ttl_s": TTL_S,
        "modo_experimento": True,
        "log_level": "WARNING",
    }
    base.update(cambios)
    return Config(**base)  # type: ignore[arg-type]


class RelojFalso:
    def __init__(self, inicio: datetime = INICIO) -> None:
        self.ahora = inicio

    def __call__(self) -> datetime:
        return self.ahora

    def avanzar(self, segundos: float) -> None:
        self.ahora += timedelta(seconds=segundos)


# --- Atajos HTTP --------------------------------------------------------------


def login(cliente: FlaskClient, usuario: str, password: str = "solventa") -> dict[str, Any]:
    respuesta = cliente.post("/v1/sesiones", json={"usuario": usuario, "password": password})
    assert respuesta.status_code == 201, respuesta.get_json()
    cuerpo: dict[str, Any] = respuesta.get_json()
    return cuerpo


def verificar(cliente: FlaskClient, token: str) -> dict[str, Any]:
    respuesta = cliente.post("/v1/sesiones/verificar", json={"token": token})
    assert respuesta.status_code == 200, respuesta.get_json()
    cuerpo: dict[str, Any] = respuesta.get_json()
    return cuerpo


def contencion(motivo: str = "OTP_FALLIDO", **cambios: str) -> dict[str, str]:
    base = {"motivo": motivo, "correlation_id": "c-1", "evento_id": "ev-1"}
    base.update(cambios)
    return base
