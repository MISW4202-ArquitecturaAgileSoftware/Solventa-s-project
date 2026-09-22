#!/usr/bin/env bash
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
[[ -f .env ]] || { echo "falta .env: copiar desde example.env" >&2; exit 1; }

# Detiene el stack. Con --volumes borra también Redis y las bases de cada
# servicio: la siguiente subida parte de semillas limpias.
docker compose down "$@"
