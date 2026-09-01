"""Tasa de detección exacta de ASR-11, cruzando journeys con incidentes.

No basta con restar contadores globales de incidentes. Dos razones:

1. **El denominador.** Un modo de fallo puede ser neutro para ciertas entradas
   (`factor_skip` no altera nada si la clase ocupacional es 1, cuyo factor ya
   vale 1.00). Esos journeys no llevan cálculo erróneo y no pertenecen al
   denominador de «cálculos erróneos detectados».

2. **El numerador.** Durante una corrida pueden registrarse incidentes que NO
   vienen del fallo inyectado —por ejemplo un `sin_quorum` porque una réplica
   sana se atascó—. Atribuirlos al modo inflaría la tasa por encima del 100 %.

Cruzando por `correlation_id` ambas cosas quedan resueltas: se cuenta cuántos de
los journeys que sí llevaban un error terminaron con un incidente registrado.
"""

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any

URL_INCIDENTES = "http://localhost:8003/v1/incidentes"


def incidentes_recientes(limite: int) -> dict[str, str]:
    """Devuelve {correlation_id: tipo} de los últimos incidentes."""
    with urllib.request.urlopen(f"{URL_INCIDENTES}?limite={limite}", timeout=30) as r:
        datos: dict[str, Any] = json.loads(r.read())
    return {i["correlation_id"]: i["tipo"] for i in datos["incidentes"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detalle", type=Path, required=True)
    parser.add_argument("--resumen", type=Path, required=True)
    parser.add_argument("--limite", type=int, default=4000)
    args = parser.parse_args()

    journeys = [
        json.loads(linea)
        for linea in args.detalle.read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]
    registrados = incidentes_recientes(args.limite)

    con_error = [j for j in journeys if j["error_inyectado"] and j["correlation_id"]]
    detectados = [j for j in con_error if j["correlation_id"] in registrados]
    sin_error = [j for j in journeys if not j["error_inyectado"] and j["correlation_id"]]
    # Incidentes en journeys SIN error inyectado: no son falsos positivos del
    # votador, son fallos reales de otra clase (una réplica sana que se atascó).
    otros = [j for j in sin_error if j["correlation_id"] in registrados]

    tipos: dict[str, int] = {}
    for j in detectados:
        tipo = registrados[j["correlation_id"]]
        tipos[tipo] = tipos.get(tipo, 0) + 1

    resumen = json.loads(args.resumen.read_text(encoding="utf-8"))
    resumen["deteccion"] = {
        "journeys": len(journeys),
        "con_error_inyectado": len(con_error),
        "detectados": len(detectados),
        "no_detectados": len(con_error) - len(detectados),
        "tasa": round(len(detectados) / len(con_error), 4) if con_error else 0.0,
        "por_tipo_de_incidente": tipos,
        "journeys_neutros": len(sin_error),
        "incidentes_en_journeys_neutros": len(otros),
    }
    args.resumen.write_text(json.dumps(resumen, indent=2, ensure_ascii=False))

    d = resumen["deteccion"]
    neutros = (
        f"  ({d['journeys_neutros']} neutros: el fallo no altera el valor)"
        if d["journeys_neutros"]
        else ""
    )
    print(
        f"    detectados {d['detectados']}/{d['con_error_inyectado']} "
        f"= {d['tasa'] * 100:.2f}%{neutros}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
