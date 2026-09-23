"""Configuración del Auditor, leída del entorno una sola vez al arrancar."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Config:
    redis_url: str
    stream_auditoria: str
    grupo: str
    #: Nombre FIJO, no el hostname: los eventos que fallan quedan en la lista de
    #: pendientes de ESTE consumidor. Si el nombre cambiara al recrear el
    #: contenedor, esos pendientes quedarían huérfanos y nunca se reintentarían.
    consumidor: str
    #: Periodo del ciclo (§5.4). Gobierna la ventana de exposición de ASR-31.
    periodo_s: float
    #: Tope de eventos por lectura; un lote lleno repite el ciclo sin dormir.
    tamano_lote: int
    url_validacion: str
    timeout_http_ms: int
    ruta_db: Path
    log_level: str


def _requerida(nombre: str) -> str:
    valor = os.environ.get(nombre)
    if not valor:
        raise RuntimeError(f"falta la variable de entorno {nombre}")
    return valor


def validar(config: Config) -> Config:
    if config.periodo_s <= 0:
        raise RuntimeError("PERIODO_AUDITORIA_S debe ser positivo")
    if config.tamano_lote <= 0:
        raise RuntimeError("TAMANO_LOTE debe ser positivo")
    return config


def desde_entorno() -> Config:
    return validar(
        Config(
            redis_url=_requerida("REDIS_URL"),
            stream_auditoria=os.environ.get("STREAM_AUDITORIA", "auditoria"),
            grupo=os.environ.get("GRUPO", "auditor"),
            consumidor=os.environ.get("CONSUMIDOR", "auditor-1"),
            periodo_s=float(os.environ.get("PERIODO_AUDITORIA_S", "5")),
            tamano_lote=int(os.environ.get("TAMANO_LOTE", "100")),
            url_validacion=_requerida("URL_VALIDACION"),
            timeout_http_ms=int(os.environ.get("TIMEOUT_HTTP_MS", "2000")),
            ruta_db=Path(os.environ.get("RUTA_DB", "/data/auditor.db")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
    )
