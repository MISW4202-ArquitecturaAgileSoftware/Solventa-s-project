#!/usr/bin/env bash
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
[[ -f .env ]] || { echo "falta .env: copiar desde example.env" >&2; exit 1; }

# Prepara el entorno local de desarrollo: venv, tooling y la libreria compartida.
# Solo para desarrollo y tests fuera de contenedor; las imagenes no lo usan.
python -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet ruff mypy pytest

if [[ -f libs/solventa-common/pyproject.toml ]]; then
  python -m pip install --quiet -e ./libs/solventa-common
else
  echo "libs/solventa-common aun no existe (se crea en F1); se omite"
fi

echo "listo. activar con: source .venv/bin/activate"
