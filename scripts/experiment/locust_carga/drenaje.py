"""Espera a que el reportero async deje de escribir incidentes.

Votación reporta en un hilo aparte. Leer `/v1/metricas` en el mismo instante
en que Locust termina subestima ASR-11.
"""

import json
import time
import urllib.request
from collections.abc import Callable

URL_METRICAS = "http://localhost:8003/v1/metricas"
SILENCIO_S = 0.5
TOPE_S = 5.0
INTERVALO_S = 0.1


def _leer_total() -> int:
    with urllib.request.urlopen(URL_METRICAS, timeout=10) as respuesta:
        datos = json.loads(respuesta.read())
    return int(datos["total"])


def esperar_metricas_estables(
    *,
    leer_total: Callable[[], int] | None = None,
    silencio_s: float = SILENCIO_S,
    tope_s: float = TOPE_S,
    intervalo_s: float = INTERVALO_S,
) -> int:
    """Devuelve `.total` cuando no crece durante `silencio_s`, o al vencer el tope."""
    obtener = leer_total or _leer_total
    inicio = time.perf_counter()
    ultimo = obtener()
    estable_desde = inicio
    while time.perf_counter() - inicio < tope_s:
        time.sleep(intervalo_s)
        actual = obtener()
        ahora = time.perf_counter()
        if actual != ultimo:
            ultimo = actual
            estable_desde = ahora
        elif ahora - estable_desde >= silencio_s:
            return actual
    return obtener()
