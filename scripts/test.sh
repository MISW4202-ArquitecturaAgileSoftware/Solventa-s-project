#!/usr/bin/env bash
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
[[ -f .env ]] || { echo "falta .env: copiar desde example.env" >&2; exit 1; }

# Tests de todo el monorepo, dentro del venv del proyecto.
[[ -d .venv ]] || { echo "falta .venv: ejecutar scripts/bootstrap.sh" >&2; exit 1; }
# shellcheck disable=SC1091
source .venv/bin/activate
ruff format --check .
ruff check .
mypy .
pytest -q "$@"
