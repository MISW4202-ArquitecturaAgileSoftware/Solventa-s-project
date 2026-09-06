#!/usr/bin/env bash
# Entrada del experimento. El protocolo vive en correr.py.
#
#   ./scripts/experiment/correr.sh
#   ./scripts/experiment/correr.sh --rapido
#   ./scripts/experiment/correr.sh --sin-ui
#   ./scripts/experiment/correr.sh --sin-pausa   # no espera Enter entre modos
#   RAPIDO=1 ./scripts/experiment/correr.sh   # sigue valiendo
#
# Tablero de resultados: http://127.0.0.1:8090
# UI Locust (carga HTTP): http://127.0.0.1:8089
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"
[[ -f .env ]] || { echo "falta .env: copiar desde example.env" >&2; exit 1; }
[[ -d .venv ]] || { echo "falta .venv: ejecutar scripts/bootstrap.sh" >&2; exit 1; }
# shellcheck disable=SC1091
source .venv/bin/activate
exec python scripts/experiment/correr.py "$@"
