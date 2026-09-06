"""Configuración de Votación."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Config:
    redis_url: str
    stream_solicitudes: str
    prefijo_respuestas: str
    log_level: str

    #: Réplicas que se espera que respondan. Define el denominador de "faltan".
    replicas_esperadas: int
    #: Coincidencias necesarias para dar consenso.
    quorum: int

    #: Presupuesto GLOBAL de recolección, no timeout por respuesta. 250 ms deja
    #: 50 ms de margen sobre los 300 ms que exige ASR-12.
    timeout_consenso_ms: int

    #: Ventana extra, tras alcanzar quórum, para recoger a las rezagadas.
    #: El veredicto ya está decidido; esperar un poco más NO cambia lo que se
    #: responde, solo permite ver a la réplica divergente y registrarla. Sin
    #: ella, ASR-12 se cumpliría y ASR-11 fallaría de forma intermitente: si las
    #: dos primeras respuestas coinciden, la tercera —la mala— nunca se leería.
    gracia_tras_quorum_ms: int

    #: Tope del stream. Sin él, la memoria de Redis crece sin límite durante una
    #: corrida de carga.
    stream_maxlen: int

    #: Expone el bloque `consenso` en la respuesta. ASR-12 exige responder sin
    #: exponer el error: true solo en desarrollo y durante el experimento.
    expose_consensus: bool

    url_gestion_errores: str
    timeout_reporte_s: float
    hilos_reporte: int

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
        stream_solicitudes=os.environ.get("STREAM_SOLICITUDES", "cot:req"),
        prefijo_respuestas=os.environ.get("PREFIJO_RESPUESTAS", "cot:resp"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        replicas_esperadas=int(os.environ.get("REPLICAS_ESPERADAS", "3")),
        quorum=int(os.environ.get("QUORUM", "2")),
        timeout_consenso_ms=int(os.environ.get("TIMEOUT_CONSENSO_MS", "250")),
        gracia_tras_quorum_ms=int(os.environ.get("GRACIA_TRAS_QUORUM_MS", "25")),
        stream_maxlen=int(os.environ.get("STREAM_MAXLEN", "10000")),
        expose_consensus=os.environ.get("EXPOSE_CONSENSUS", "false").lower() == "true",
        url_gestion_errores=_requerida("URL_GESTION_ERRORES"),
        timeout_reporte_s=float(os.environ.get("TIMEOUT_REPORTE_MS", "2000")) / 1000,
        hilos_reporte=int(os.environ.get("HILOS_REPORTE", "4")),
    )
