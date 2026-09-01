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

    #: Tope de la cola en memoria del escritor. Si se llena, encolar falla en
    #: vez de bloquear: hacer esperar a Votación consumiría su presupuesto de
    #: latencia, que es justo lo que ASR-12 mide.
    capacidad_cola: int


def desde_entorno() -> Config:
    return Config(
        ruta_incidentes=Path(os.environ.get("RUTA_INCIDENTES", "/datos/incidentes.jsonl")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        capacidad_cola=int(os.environ.get("CAPACIDAD_COLA", "10000")),
    )
