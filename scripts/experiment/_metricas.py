"""Lee las métricas de GestorErrores.

`esperar` bloquea hasta que la cola del escritor se vacía. Es necesario porque
el registro de incidentes es asíncrono a propósito: leer el contador con
escrituras pendientes contaría de menos y falsearía a la baja la tasa de
detección de ASR-11.
"""

import json
import sys
import time
import urllib.request
from typing import Any

URL = "http://localhost:8003/v1/metricas"


def leer() -> dict[str, Any]:
    with urllib.request.urlopen(URL, timeout=10) as respuesta:
        datos: dict[str, Any] = json.loads(respuesta.read())
        return datos


def esperar(timeout: float = 30.0) -> dict[str, Any]:
    limite = time.perf_counter() + timeout
    while True:
        datos = leer()
        if datos["pendientes_de_escritura"] == 0 or time.perf_counter() > limite:
            return datos
        time.sleep(0.2)


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "total"
    datos = esperar() if modo != "raw" else leer()
    if modo == "total":
        print(datos["total"])
    else:
        print(json.dumps(datos))
