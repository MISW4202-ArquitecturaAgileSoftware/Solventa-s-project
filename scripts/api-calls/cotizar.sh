#!/usr/bin/env bash
# Lanza una cotización contra Votación y resume el veredicto.
#
#   ./scripts/api-calls/cotizar.sh [ruta-solicitud.json]
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"
# shellcheck disable=SC1091
set -a; source .env; set +a

SOLICITUD="${1:-docs/ejemplos/solicitud.json}"

curl -s -XPOST "localhost:${PUERTO_VOTACION}/v1/cotizaciones" \
     -H 'content-type: application/json' -d "@$SOLICITUD" \
  | python "$RAIZ/scripts/api-calls/_formatear_cotizacion.py"
