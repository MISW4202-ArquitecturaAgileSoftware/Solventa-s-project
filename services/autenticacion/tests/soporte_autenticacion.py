"""Helpers de prueba con nombre único en el monorepo.

No viven en `conftest.py` porque cada servicio tiene el suyo y, al correr mypy
desde la raíz, todos resolverían al mismo módulo `conftest`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autenticacion.config import Config


def configuracion(tmp_path: Path, **cambios: object) -> Config:
    base: dict[str, object] = {
        "ruta_db": tmp_path / "autenticacion.db",
        "jwt_secret": "secreto-de-prueba",
        "jwt_ttl_s": 3600,
        "modo_experimento": True,
        "log_level": "WARNING",
    }
    base.update(cambios)
    return Config(**base)  # type: ignore[arg-type]
