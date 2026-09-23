"""Configuración de Autenticación, leída una vez del entorno."""

import os
from dataclasses import dataclass
from pathlib import Path

#: RFC 7518 §3.2: la clave de HS256 debe tener al menos el tamaño del hash
#: (256 bits). PyJWT solo avisa con `InsecureKeyLengthWarning`; aquí se falla
#: al arrancar, que es cuando el error es barato de corregir.
LONGITUD_MINIMA_SECRETO = 32


@dataclass(frozen=True, slots=True)
class Config:
    ruta_db: Path
    #: Solo Autenticación conoce el secreto: para el resto el token es opaco.
    jwt_secret: str
    #: Vida del token. Larga a propósito: no debe interferir con las mediciones.
    jwt_ttl_s: int
    #: Habilita la ruta que simula al atacante alterando un rol.
    modo_experimento: bool
    log_level: str


def _requerida(nombre: str) -> str:
    valor = os.environ.get(nombre)
    if not valor:
        raise RuntimeError(f"falta la variable de entorno {nombre}")
    return valor


def validar(config: Config) -> Config:
    if len(config.jwt_secret.encode("utf-8")) < LONGITUD_MINIMA_SECRETO:
        raise RuntimeError(
            f"JWT_SECRET debe tener al menos {LONGITUD_MINIMA_SECRETO} bytes (HS256, RFC 7518 §3.2)"
        )
    if config.jwt_ttl_s <= 0:
        raise RuntimeError("JWT_TTL_S debe ser un entero positivo")
    return config


def desde_entorno() -> Config:
    return validar(
        Config(
            ruta_db=Path(os.environ.get("RUTA_DB", "/data/autenticacion.db")),
            jwt_secret=_requerida("JWT_SECRET"),
            jwt_ttl_s=int(os.environ.get("JWT_TTL_S", "3600")),
            modo_experimento=os.environ.get("MODO_EXPERIMENTO", "false").lower() == "true",
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
    )
