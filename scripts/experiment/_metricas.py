"""Lee las métricas persistidas por Gestión de Errores."""

import json
import sys
import urllib.request
from typing import Any

URL = "http://localhost:8003/v1/metricas"


def leer() -> dict[str, Any]:
    with urllib.request.urlopen(URL, timeout=10) as respuesta:
        datos: dict[str, Any] = json.loads(respuesta.read())
        return datos


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "total"
    datos = leer()
    if modo == "total":
        print(datos["total"])
    else:
        print(json.dumps(datos))
