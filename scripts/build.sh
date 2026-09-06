#!/usr/bin/env bash
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
[[ -f .env ]] || { echo "falta .env: copiar desde example.env" >&2; exit 1; }

# Construye las imágenes; cada servicio usa su propia carpeta como contexto.
# pip durante el build usa la red del host (build.network en los compose).
docker compose build "$@"
