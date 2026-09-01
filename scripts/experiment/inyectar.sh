#!/usr/bin/env bash
# Reinicia una réplica con un modo de fallo y espera a que quede sana.
#
#   ./scripts/experiment/inyectar.sh b premium_offset
#   ./scripts/experiment/inyectar.sh b none          # restaura
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"

REPLICA="${1:?uso: inyectar.sh <a|b|c> <modo>}"
MODO="${2:?uso: inyectar.sh <a|b|c> <modo>}"
VARIABLE="FAULT_$(echo "$REPLICA" | tr '[:lower:]' '[:upper:]')"

export "${VARIABLE}=${MODO}"
docker compose up -d --wait "cotizador-${REPLICA}" >/dev/null 2>&1

# Verificar que el contenedor arrancó realmente con el modo pedido: un fallo
# silencioso aquí invalidaría toda la corrida sin que se notara.
APLICADO="$(docker compose exec -T "cotizador-${REPLICA}" printenv FAULT_MODE)"
if [[ "$APLICADO" != "$MODO" ]]; then
  echo "FALLO: se pidió $MODO pero la réplica corre con $APLICADO" >&2
  exit 1
fi
echo "cotizador-${REPLICA}: FAULT_MODE=${APLICADO}"
