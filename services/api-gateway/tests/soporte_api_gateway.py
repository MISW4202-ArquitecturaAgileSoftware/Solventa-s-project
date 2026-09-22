"""Helpers de prueba con nombre único en el monorepo.

No viven en `conftest.py` porque cada servicio tiene el suyo y, al correr mypy
desde la raíz, todos resolverían al mismo módulo `conftest`.
"""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api_gateway.config import Config
from api_gateway.http import RespuestaInterna

URL_AUTENTICACION = "http://autenticacion.test"
URL_VALIDACION = "http://validacion.test"


def configuracion(**cambios: object) -> Config:
    base: dict[str, object] = {
        "url_autenticacion": URL_AUTENTICACION,
        "url_validacion": URL_VALIDACION,
        "upstream_timeout_ms": 3000,
        "log_level": "WARNING",
    }
    base.update(cambios)
    return Config(**base)  # type: ignore[arg-type]


def ok(cuerpo: Any, estado: int = 200, content_type: str = "application/json") -> RespuestaInterna:
    return RespuestaInterna(estado=estado, cuerpo=cuerpo, content_type=content_type)


class ClienteHttpDoble:
    """Doble inyectable de `ClienteHttp`: registra `(url, json, correlation_id)`
    y responde según lo configurado con `cuando`, por URL."""

    def __init__(self) -> None:
        self.llamadas: list[tuple[str, Any, str]] = []
        self._respuestas: dict[str, RespuestaInterna | Exception] = {}

    def cuando(self, url: str, respuesta: RespuestaInterna | Exception) -> None:
        self._respuestas[url] = respuesta

    def post(self, url: str, json: Any, correlation_id: str) -> RespuestaInterna:
        self.llamadas.append((url, json, correlation_id))
        configurada = self._respuestas.get(url)
        if configurada is None:
            raise AssertionError(f"sin respuesta configurada para {url}")
        if isinstance(configurada, Exception):
            raise configurada
        return configurada
