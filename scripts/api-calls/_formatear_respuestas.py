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

print(f"{'réplica':<8} {'estado':<7} {'prima_mensual':>14} {'ms':>4}  resultado_hash")
for fila in sorted(filas, key=lambda f: f["cotizador_id"]):
    resultado = fila.get("resultado") or {}
    prima = resultado.get("prima_mensual", "-")
    huella = (fila.get("resultado_hash") or "-")[:16]
    print(
        f"{fila['cotizador_id']:<8} {fila['estado']:<7} {prima:>14} "
        f"{fila['duracion_ms']:>4}  {huella}"
    )

hashes = {f.get("resultado_hash") for f in filas if f.get("resultado_hash")}
print()
print(f"respuestas: {len(filas)} | hashes distintos: {len(hashes)}")
