"""Escribe la tasa de detección de una corrida B sobre su JSON."""

import json
import sys
from pathlib import Path
from typing import Any


def anotar(ruta: Path, modo: str, antes: int, despues: int) -> dict[str, Any]:
    datos: dict[str, Any] = json.loads(ruta.read_text(encoding="utf-8"))
    datos["modo"] = modo
    datos["incidentes_registrados"] = despues - antes
    den = int(datos["fallos_efectivos"])
    if den == 0:
        raise SystemExit(
            f"FALLO: {modo} no produjo ningún fallo efectivo; no se puede calcular la tasa"
        )
    datos["tasa_deteccion"] = round((despues - antes) / den, 4)
    ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return datos


if __name__ == "__main__":
    ruta, modo, antes, despues = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    datos = anotar(ruta, modo, antes, despues)
    print(
        f"    detectados {datos['incidentes_registrados']}/{datos['fallos_efectivos']} "
        f"= {datos['tasa_deteccion'] * 100:.2f}%"
    )
