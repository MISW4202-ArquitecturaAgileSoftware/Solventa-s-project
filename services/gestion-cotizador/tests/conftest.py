"""Hace importable `gestion_cotizador` en los tests locales.

El servicio no se instala como paquete —la decisión de layout fue
`requirements.txt` por servicio, sin workspace—, así que su `src/` se añade al
path. Dentro de la imagen no hace falta: el Dockerfile fija `PYTHONPATH`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
