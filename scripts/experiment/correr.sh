#!/usr/bin/env bash
# Ejecuta el experimento completo: línea base, detección por modo de fallo y
# enmascaramiento sostenido. Escribe un JSON por corrida en resultados/.
#
#   ./scripts/experiment/correr.sh            # completo (~38 min)
#   RAPIDO=1 ./scripts/experiment/correr.sh   # versión corta, para depurar
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"
# shellcheck disable=SC1091
source .venv/bin/activate

RES="scripts/experiment/resultados"
CARGA="python scripts/experiment/carga.py"
MET="python scripts/experiment/_metricas.py"
mkdir -p "$RES"

POR_MINUTO="${POR_MINUTO:-500}"
if [[ -n "${RAPIDO:-}" ]]; then
  N_BASE=200; N_MODO=100; N_MASCARA=200
else
  # 10 min de línea base y de enmascaramiento; 1000 cotizaciones por modo.
  N_BASE=5000; N_MODO=1000; N_MASCARA=5000
fi

MODOS=(premium_offset factor_skip rate_table_stale rounding_drift
       out_of_range silent_zero slow crash)

restaurar() {
  ./scripts/experiment/inyectar.sh a none >/dev/null
  ./scripts/experiment/inyectar.sh b none >/dev/null
  ./scripts/experiment/inyectar.sh c none >/dev/null
}

echo "### preparación: réplicas sanas y evidencia a cero"
restaurar
docker compose exec -T gestion-errores sh -c '> /datos/incidentes.jsonl'
docker compose restart gestion-errores >/dev/null 2>&1
docker compose up -d --wait >/dev/null 2>&1
rm -f "$RES"/*.json
echo "incidentes iniciales: $($MET total)"

echo
echo "### CORRIDA A — línea base (sin fallo), $N_BASE cotizaciones"
$CARGA --etiqueta baseline --n "$N_BASE" --por-minuto "$POR_MINUTO" \
       --salida "$RES/A-baseline.json"

echo
echo "### CORRIDA B — detección, $N_MODO cotizaciones por modo"
for MODO in "${MODOS[@]}"; do
  echo "--- $MODO"
  ./scripts/experiment/inyectar.sh b "$MODO"
  ANTES="$($MET total)"
  $CARGA --etiqueta "deteccion-$MODO" --n "$N_MODO" --por-minuto "$POR_MINUTO" \
         --salida "$RES/B-$MODO.json"
  DESPUES="$($MET total)"
  python - "$RES/B-$MODO.json" "$MODO" "$ANTES" "$DESPUES" <<'PY'
import json, sys
ruta, modo, antes, despues = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
datos = json.loads(open(ruta).read())
datos["modo"] = modo
datos["incidentes_registrados"] = despues - antes
den = datos["alcanzaron_votacion"]
datos["tasa_deteccion"] = round((despues - antes) / den, 4) if den else 0.0
open(ruta, "w").write(json.dumps(datos, indent=2, ensure_ascii=False))
print(f"    detectados {datos['incidentes_registrados']}/{den} "
      f"= {datos['tasa_deteccion'] * 100:.2f}%")
PY
done
restaurar

echo
echo "### CORRIDA C — enmascaramiento sostenido con premium_offset en B"
./scripts/experiment/inyectar.sh b premium_offset
$CARGA --etiqueta enmascaramiento --n "$N_MASCARA" --por-minuto "$POR_MINUTO" \
       --salida "$RES/C-enmascaramiento.json"
restaurar

echo
echo "### informe"
python scripts/experiment/reporte.py
