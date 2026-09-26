#!/usr/bin/env bash
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"
# Un clon nuevo no trae .env ni .venv. Se crean aquí para que baste
# ejecutar este script.
if [[ ! -f .env ]]; then
  cp example.env .env
  echo "creado .env desde example.env"
fi
if [[ ! -d .venv ]]; then
  echo "no hay .venv; ejecutando scripts/bootstrap.sh"
  ./scripts/bootstrap.sh
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python scripts/experiment/correr.py "$@"
