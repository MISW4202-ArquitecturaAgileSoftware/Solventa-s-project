"""Helpers de prueba con nombre único en el monorepo.

No viven en `conftest.py` porque cada servicio tiene el suyo y, al correr mypy
desde la raíz, todos resolverían al mismo módulo `conftest`.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gestion_cotizador.config import Config

FECHA_CALCULO = date(2026, 8, 31)


def configuracion(**cambios: object) -> Config:
    base: dict[str, object] = {
        "redis_url": "redis://redis:6379/0",
        "stream_cotizador": "sol:cotizador",
        "prefijo_respuestas": "resp",
        "ttl_respuestas_s": 60,
        "tarifario_version": "2026.02",
        "grupo": "gestion-cotizador",
        "consumidor": "worker-prueba",
        "block_ms": 1000,
        "log_level": "WARNING",
    }
    base.update(cambios)
    return Config(**base)  # type: ignore[arg-type]
