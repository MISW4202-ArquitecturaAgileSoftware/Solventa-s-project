"""Logging JSON pequeño para correlacionar las solicitudes del experimento."""

import json
import logging
from datetime import UTC, datetime
from typing import Any


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        datos = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        datos.update(getattr(record, "event_fields", {}))
        return json.dumps(datos, ensure_ascii=False)


def configurar_logging(nivel: str) -> None:
    manejador = logging.StreamHandler()
    manejador.setFormatter(_JsonFormatter())
    logger = logging.getLogger("api_gateway")
    logger.handlers.clear()
    logger.addHandler(manejador)
    logger.setLevel(nivel.upper())
    logger.propagate = False


def registrar_log(nivel: int, evento: str, **campos: Any) -> None:
    logging.getLogger("api_gateway").log(
        nivel,
        evento,
        extra={"event_fields": campos},
    )
