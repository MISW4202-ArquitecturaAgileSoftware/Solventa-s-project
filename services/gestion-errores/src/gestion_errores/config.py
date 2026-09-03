"""Configuración del servicio, leída del entorno al construir la app."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Config:
    #: Fichero JSONL donde se acumulan los incidentes. Vive en un volumen
    #: nombrado: borrar el contenedor no puede perder la evidencia.
    ruta_incidentes: Path
    log_level: str


def desde_entorno() -> Config:
    return Config(
        ruta_incidentes=Path(os.environ.get("RUTA_INCIDENTES", "/datos/incidentes.jsonl")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
