"""Configuración de api-gateway."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Config:
    url_autenticacion: str
    url_validacion: str
    #: Máximo de espera por una llamada a un servicio interno.
    upstream_timeout_ms: int
    log_level: str


def _requerida(nombre: str) -> str:
    valor = os.environ.get(nombre)
    if not valor:
        raise RuntimeError(f"falta la variable de entorno {nombre}")
    return valor


def desde_entorno() -> Config:
    return Config(
        url_autenticacion=_requerida("URL_AUTENTICACION"),
        url_validacion=_requerida("URL_VALIDACION"),
        upstream_timeout_ms=int(os.environ.get("UPSTREAM_TIMEOUT_MS", "3000")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
