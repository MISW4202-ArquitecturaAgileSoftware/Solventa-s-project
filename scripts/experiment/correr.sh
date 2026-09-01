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
# El generador necesita alcanzar `cotizador.faults` para saber si un modo
# altera realmente el resultado de cada entrada concreta.
export PYTHONPATH="$RAIZ/services/cotizador/src${PYTHONPATH:+:$PYTHONPATH}"

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

SOLO_B="${SOLO_B:-}"

echo "### preparación: réplicas sanas y evidencia a cero"
restaurar
docker compose exec -T gestion-errores sh -c '> /datos/incidentes.jsonl'
docker compose restart gestion-errores >/dev/null 2>&1
docker compose up -d --wait >/dev/null 2>&1
if [[ -z "$SOLO_B" ]]; then rm -f "$RES"/*.json "$RES"/*.jsonl; else rm -f "$RES"/B-*; fi
echo "incidentes iniciales: $($MET total)"

if [[ -z "$SOLO_B" ]]; then
echo
echo "### CORRIDA A — línea base (sin fallo), $N_BASE cotizaciones"
$CARGA --etiqueta baseline --n "$N_BASE" --por-minuto "$POR_MINUTO" \
       --salida "$RES/A-baseline.json"
fi

echo
echo "### CORRIDA B — detección, $N_MODO cotizaciones por modo"
for MODO in "${MODOS[@]}"; do
  echo "--- $MODO"
  ./scripts/experiment/inyectar.sh b "$MODO"
  $CARGA --etiqueta "deteccion-$MODO" --n "$N_MODO" --por-minuto "$POR_MINUTO" \
         --modo-fallo "$MODO" --salida "$RES/B-$MODO.json"
  # Espera a que el escritor asíncrono vacíe su cola: leer antes contaría de menos.
  $MET total >/dev/null
  python scripts/experiment/_deteccion.py \
      --detalle "$RES/B-$MODO.detalle.jsonl" --resumen "$RES/B-$MODO.json" \
      --limite $((N_MODO * 2))
done
restaurar

if [[ -z "$SOLO_B" ]]; then
echo
echo "### CORRIDA C — enmascaramiento sostenido con premium_offset en B"
./scripts/experiment/inyectar.sh b premium_offset
$CARGA --etiqueta enmascaramiento --n "$N_MASCARA" --por-minuto "$POR_MINUTO" \
       --modo-fallo premium_offset --salida "$RES/C-enmascaramiento.json"
restaurar
fi

echo
echo "### informe"
python scripts/experiment/reporte.py
