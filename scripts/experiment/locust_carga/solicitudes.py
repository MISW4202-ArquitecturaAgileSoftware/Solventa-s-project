"""Solicitudes deterministas del generador de carga."""

from datetime import date, timedelta
from typing import Any

CANALES = ["banco_aliado", "retail", "directo"]
SUMAS = ["80000000.00", "150000000.00", "250000000.00", "400000000.00", "900000000.00"]
PLAZOS = [60, 120, 180, 240, 300]
CLASES = [1, 2, 3, 4]
# Edades repartidas por los seis tramos del tarifario.
EDADES = [22, 27, 33, 38, 44, 47, 52, 57, 63, 68, 71, 74]


def solicitud_de(indice: int, hoy: date) -> dict[str, Any]:
    """Solicitud determinista a partir del índice.

    Los pasos son primos entre sí con las longitudes de las listas para que las
    combinaciones no se repitan en ciclos cortos.
    """
    edad = EDADES[indice % len(EDADES)]
    nacimiento = date(hoy.year - edad, 1, 1) + timedelta(days=(indice * 7) % 300)
    return {
        "request_id": f"experiment-{indice:08d}",
        "producto": "vida_hipotecario",
        "moneda": "COP",
        "suma_asegurada": SUMAS[(indice * 3) % len(SUMAS)],
        "plazo_meses": PLAZOS[(indice * 2) % len(PLAZOS)],
        "canal": CANALES[indice % len(CANALES)],
        "asegurado": {
            "fecha_nacimiento": nacimiento.isoformat(),
            "genero": "FMX"[indice % 3],
            "fumador": indice % 4 == 0,
            "clase_ocupacional": CLASES[(indice * 5) % len(CLASES)],
        },
        "consentimiento_open_finance": True,
    }
