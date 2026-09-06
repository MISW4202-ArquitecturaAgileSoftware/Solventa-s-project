"""Formatea en tabla las respuestas de las réplicas para un correlation_id.

Archivo aparte y no un heredoc dentro del script de shell: `cmd | python - <<EOF`
redirige el heredoc a stdin y anula la tubería, de modo que el script leería su
propio código en lugar de los datos.
"""

import json
import sys

filas = [json.loads(linea) for linea in sys.stdin if linea.strip()]
if not filas:
    print("(sin respuestas)")
    raise SystemExit(1)

print(f"{'réplica':<8} {'estado':<7} {'prima_mensual':>14} {'ms':>4}")
for fila in sorted(filas, key=lambda f: f["cotizador_id"]):
    resultado = fila.get("resultado") or {}
    prima = resultado.get("prima_mensual", "-")
    print(f"{fila['cotizador_id']:<8} {fila['estado']:<7} {prima:>14} {fila['duracion_ms']:>4}")

print(f"\nrespuestas: {len(filas)}")
