"""Configuración de Gestión de Pólizas, leída del entorno una sola vez al arrancar."""

import os
import socket
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Config:
    redis_url: str
    stream_polizas: str
    prefijo_respuestas: str
    stream_auditoria: str
    stream_maxlen: int
    #: Vida de la lista de respuestas. Si Validación ya se rindió, la lista
    #: queda huérfana; sin expiración sería una fuga de memoria por cada operación.
    ttl_respuestas_s: int
    ruta_db: Path
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
        stream_polizas=os.environ.get("STREAM_POLIZAS", "sol:polizas"),
        prefijo_respuestas=os.environ.get("PREFIJO_RESPUESTAS", "resp"),
        stream_auditoria=os.environ.get("STREAM_AUDITORIA", "auditoria"),
        stream_maxlen=int(os.environ.get("STREAM_MAXLEN", "10000")),
        ttl_respuestas_s=int(os.environ.get("TTL_RESPUESTAS_S", "60")),
        ruta_db=Path(os.environ.get("RUTA_DB", "/data/polizas.db")),
        grupo=os.environ.get("GRUPO", "gestion-polizas"),
        # Sin defecto explícito en el entorno: el hostname del contenedor ya es
        # un identificador único y estable durante la vida del proceso.
        consumidor=os.environ.get("CONSUMIDOR", socket.gethostname()),
        block_ms=int(os.environ.get("BLOCK_MS", "1000")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
