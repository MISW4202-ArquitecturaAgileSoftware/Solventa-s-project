"""Configuración del Auditor, leída del entorno una sola vez al arrancar."""

import os
import socket
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Config:
    redis_url: str
    stream_auditoria: str
    #: Solo Validación conoce el alcance autorizado; el Auditor le pregunta.
    url_validacion: str
    #: Gobierna la ventana de exposición de ASR-31 (PLAN-IMPLEMENTACION.md §5.4).
    periodo_auditoria_s: float
    lote: int
    timeout_http_ms: int
    ruta_db: Path
    grupo: str
    consumidor: str
    log_level: str


def _requerida(nombre: str) -> str:
    valor = os.environ.get(nombre)
    if not valor:
        raise RuntimeError(f"falta la variable de entorno {nombre}")
    return valor


def desde_entorno() -> Config:
    return Config(
        redis_url=_requerida("REDIS_URL"),
        stream_auditoria=os.environ.get("STREAM_AUDITORIA", "auditoria"),
        url_validacion=_requerida("URL_VALIDACION"),
        periodo_auditoria_s=float(os.environ.get("PERIODO_AUDITORIA_S", "5")),
        lote=int(os.environ.get("LOTE", "100")),
        timeout_http_ms=int(os.environ.get("TIMEOUT_HTTP_MS", "2000")),
        ruta_db=Path(os.environ.get("RUTA_DB", "/data/auditor.db")),
        grupo=os.environ.get("GRUPO", "auditor"),
        consumidor=os.environ.get("CONSUMIDOR", socket.gethostname()),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
