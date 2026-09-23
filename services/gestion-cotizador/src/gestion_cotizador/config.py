"""Configuración de Gestión-Cotizador, leída del entorno una sola vez al arrancar.

12-factor: nada de valores por defecto que oculten una variable ausente cuando
la variable es esencial. `REDIS_URL` es la única sin defecto: sin cola no hay
worker.
"""

import os
import socket
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Config:
    redis_url: str
    stream_cotizador: str
    prefijo_respuestas: str
    ttl_respuestas_s: int
    tarifario_version: str
    grupo: str
    consumidor: str
    #: Cuánto bloquea cada XREADGROUP. Corto para que SIGTERM se atienda rápido.
    block_ms: int
    log_level: str

    def clave_respuestas(self, correlation_id: str) -> str:
        return f"{self.prefijo_respuestas}:{correlation_id}"


def _requerida(nombre: str) -> str:
    valor = os.environ.get(nombre)
    if not valor:
        raise RuntimeError(f"falta la variable de entorno {nombre}")
    return valor


def desde_entorno() -> Config:
    return Config(
        redis_url=_requerida("REDIS_URL"),
        stream_cotizador=os.environ.get("STREAM_COTIZADOR", "sol:cotizador"),
        prefijo_respuestas=os.environ.get("PREFIJO_RESPUESTAS", "resp"),
        ttl_respuestas_s=int(os.environ.get("TTL_RESPUESTAS_S", "60")),
        tarifario_version=os.environ.get("TARIFARIO_VERSION", "2026.02"),
        grupo=os.environ.get("GRUPO", "gestion-cotizador"),
        consumidor=os.environ.get("CONSUMIDOR") or socket.gethostname(),
        block_ms=int(os.environ.get("BLOCK_MS", "1000")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
