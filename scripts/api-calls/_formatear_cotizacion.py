"""Resume en una línea el veredicto de una cotización.

Archivo aparte y no `python -c`: el JSON lleva comillas dobles y escaparlas
dentro de una cadena de shell es una fuente de errores sin ninguna ventaja.
"""

import json
import sys

respuesta = json.load(sys.stdin)

if respuesta.get("status", 200) >= 400:
    detalle = str(respuesta.get("detail", ""))[:70]
    print(f"  HTTP {respuesta['status']}  {respuesta.get('title')}  ({detalle})")
    raise SystemExit(0)

consenso = respuesta.get("consenso", {})
print(
    f"  estado={respuesta['estado']:<20}"
    f" prima={respuesta['cotizacion']['prima_mensual']:>13}"
    f" resp={consenso.get('respuestas_recibidas')}"
    f" acuerdo={consenso.get('acuerdo')}"
    f" divergencia={consenso.get('divergencia_detectada')!s:<5}"
    f" {consenso.get('replicas_divergentes')}"
    f" lat={consenso.get('latencia_consenso_ms')}ms"
    f" corte={consenso.get('corte')}"
)
