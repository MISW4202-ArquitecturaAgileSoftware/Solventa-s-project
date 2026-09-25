#!/usr/bin/env bash
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
[[ -f .env ]] || { echo "falta .env: copiar desde example.env" >&2; exit 1; }

# Prepara el entorno local de desarrollo y las herramientas de validación.
# Solo para desarrollo y tests fuera de contenedor; las imágenes no lo usan.
# Cada servicio declara sus dependencias en su propia carpeta; aquí solo se
# instalan todas en un mismo venv para poder correr la suite completa.
[[ -d .venv ]] || python -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet ruff mypy pytest
for req in services/*/requirements-dev.txt scripts/experiment/requirements.txt; do
  [[ -f "$req" ]] && python -m pip install --quiet -r "$req"
done

echo "listo. activar con: source .venv/bin/activate"
