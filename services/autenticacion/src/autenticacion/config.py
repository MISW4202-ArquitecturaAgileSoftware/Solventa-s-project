"""Configuración de Autenticación."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Config:
    ruta_db: Path
    #: Solo Autenticación conoce el secreto: para el resto el token es opaco.
    jwt_secret: str
    #: Vida del token en segundos. Larga a propósito: la expiración no debe
    #: interferir con las mediciones del experimento.
    jwt_ttl_s: int
    #: Habilita la ruta que simula la alteración de rol del atacante.
    modo_experimento: bool
    log_level: str


def _requerida(nombre: str) -> str:
    valor = os.environ.get(nombre)
    if not valor:
        raise RuntimeError(f"falta la variable de entorno {nombre}")
    return valor


def desde_entorno() -> Config:
    return Config(
        ruta_db=Path(os.environ.get("RUTA_DB", "/data/autenticacion.db")),
        jwt_secret=_requerida("JWT_SECRET"),
        jwt_ttl_s=int(os.environ.get("JWT_TTL_S", "3600")),
        modo_experimento=os.environ.get("MODO_EXPERIMENTO", "false").lower() == "true",
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
