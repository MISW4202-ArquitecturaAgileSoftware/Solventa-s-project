"""Configuración del worker, leída del entorno una sola vez al arrancar.

12-factor: nada de valores por defecto que oculten una variable ausente cuando
la variable es esencial. `COTIZADOR_ID` no tiene defecto a propósito: una
réplica sin identidad no puede participar en una votación.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Config:
    cotizador_id: str
    redis_url: str
    stream_solicitudes: str
    prefijo_respuestas: str
    fault_mode: str
    tarifario_version: str
    log_level: str

    # Segundos de vida de la clave de latido. El healthcheck del contenedor la
    # busca; si el bucle consumidor se cuelga, la clave expira y la réplica se
    # declara enferma. Debe ser mayor que una vuelta del bucle (~1 s) con
    # holgura, y menor que el producto de `interval` por `retries` del healthcheck.
    ttl_latido_s: int

    # Vida de la lista de respuestas. Si Votación ya se rindió, la lista queda
    # huérfana; sin expiración sería una fuga de memoria por cada cotización.
    ttl_respuestas_s: int

    # Cuánto bloquea cada XREADGROUP. Corto para que SIGTERM se atienda rápido.
    block_ms: int

    @property
    def grupo(self) -> str:
        """Un consumer group por réplica: eso es lo que produce el fan-out."""
        return f"grupo-{self.cotizador_id.lower()}"

    @property
    def consumidor(self) -> str:
        return f"consumidor-{self.cotizador_id.lower()}"

    @property
    def clave_latido(self) -> str:
        return f"cot:hb:{self.cotizador_id.lower()}"

    def clave_respuestas(self, correlation_id: str) -> str:
        return f"{self.prefijo_respuestas}:{correlation_id}"


def _requerida(nombre: str) -> str:
    valor = os.environ.get(nombre)
    if not valor:
        raise RuntimeError(f"falta la variable de entorno {nombre}")
    return valor


def desde_entorno() -> Config:
    return Config(
        cotizador_id=_requerida("COTIZADOR_ID"),
        redis_url=_requerida("REDIS_URL"),
        stream_solicitudes=os.environ.get("STREAM_SOLICITUDES", "cot:req"),
        prefijo_respuestas=os.environ.get("PREFIJO_RESPUESTAS", "cot:resp"),
        fault_mode=os.environ.get("FAULT_MODE", "none"),
        tarifario_version=os.environ.get("TARIFARIO_VERSION", "2026.02"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        ttl_latido_s=int(os.environ.get("TTL_LATIDO_S", "15")),
        ttl_respuestas_s=int(os.environ.get("TTL_RESPUESTAS_S", "60")),
        block_ms=int(os.environ.get("BLOCK_MS", "1000")),
    )
