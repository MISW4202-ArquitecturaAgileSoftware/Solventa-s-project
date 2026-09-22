"""Configuración de Validación, incluida la de su proceso interno de Reacción."""

import os
import socket
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Config:
    ruta_db: Path
    redis_url: str
    stream_polizas: str
    stream_cotizador: str
    prefijo_respuestas: str
    stream_seguridad: str
    #: Tope de cada stream: sin él la memoria de Redis crece sin límite bajo carga.
    stream_maxlen: int
    #: Presupuesto de espera por la respuesta de un worker antes de 504.
    timeout_respuesta_ms: int
    #: Habilita el canal OTP simulado y la ruta de experimento.
    modo_experimento: bool
    log_level: str

    # --- Reacción: el proceso de contención vive dentro de este contenedor ---
    #: Arranca el hilo consumidor de `seguridad`. Los tests lo apagan para
    #: ejercitar el consumidor de forma síncrona.
    reaccion_activa: bool
    #: Reacción es quien revoca y bloquea en Autenticación.
    url_autenticacion: str
    timeout_http_ms: int
    grupo_reaccion: str
    consumidor_reaccion: str
    #: Cuánto bloquea cada XREADGROUP de eventos nuevos y cuánto se espera
    #: antes de reintentar un pendiente que volvió a fallar.
    block_ms: int


def _requerida(nombre: str) -> str:
    valor = os.environ.get(nombre)
    if not valor:
        raise RuntimeError(f"falta la variable de entorno {nombre}")
    return valor


def desde_entorno() -> Config:
    return Config(
        ruta_db=Path(os.environ.get("RUTA_DB", "/data/validacion.db")),
        redis_url=_requerida("REDIS_URL"),
        stream_polizas=os.environ.get("STREAM_POLIZAS", "sol:polizas"),
        stream_cotizador=os.environ.get("STREAM_COTIZADOR", "sol:cotizador"),
        prefijo_respuestas=os.environ.get("PREFIJO_RESPUESTAS", "resp"),
        stream_seguridad=os.environ.get("STREAM_SEGURIDAD", "seguridad"),
        stream_maxlen=int(os.environ.get("STREAM_MAXLEN", "10000")),
        timeout_respuesta_ms=int(os.environ.get("TIMEOUT_RESPUESTA_MS", "2000")),
        modo_experimento=os.environ.get("MODO_EXPERIMENTO", "false").lower() == "true",
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        reaccion_activa=os.environ.get("REACCION_ACTIVA", "true").lower() == "true",
        url_autenticacion=_requerida("URL_AUTENTICACION"),
        timeout_http_ms=int(os.environ.get("TIMEOUT_HTTP_MS", "2000")),
        grupo_reaccion=os.environ.get("GRUPO_REACCION", "reaccion"),
        consumidor_reaccion=os.environ.get("CONSUMIDOR_REACCION") or socket.gethostname(),
        block_ms=int(os.environ.get("BLOCK_MS", "1000")),
    )
