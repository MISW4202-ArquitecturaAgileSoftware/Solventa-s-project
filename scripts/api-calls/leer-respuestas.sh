#!/usr/bin/env bash
# Muestra, en tabla, las respuestas depositadas por las réplicas para un
# correlation_id. Es la lectura que valida F3.
#
#   ./scripts/api-calls/leer-respuestas.sh <correlation_id>
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"

CID="${1:?uso: leer-respuestas.sh <correlation_id>}"

docker compose exec -T redis redis-cli LRANGE "cot:resp:$CID" 0 -1 \
  | python "$RAIZ/scripts/api-calls/_formatear_respuestas.py"
