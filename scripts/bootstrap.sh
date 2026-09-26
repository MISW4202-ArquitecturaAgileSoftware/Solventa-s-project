#!/usr/bin/env bash
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
if [[ ! -f .env ]]; then
  cp example.env .env
  echo "creado .env desde example.env"
fi

# Prepara el entorno local de desarrollo y las herramientas de validación.
# Solo para desarrollo y tests fuera de contenedor; las imágenes no lo usan.
# Cada servicio declara sus dependencias en su propia carpeta; aquí solo se
# instalan todas en un mismo venv para poder correr la suite completa.
if [[ ! -d .venv ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
  elif command -v python >/dev/null 2>&1; then
    PYTHON=python
  else
    echo "error: no se encontró Python; instala Python 3.14 y vuelve a ejecutar este script" >&2
    exit 1
  fi
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet ruff mypy pytest
for req in services/*/requirements-dev.txt scripts/experiment/requirements.txt; do
  [[ -f "$req" ]] && python -m pip install --quiet -r "$req"
done

echo "listo. activar con: source .venv/bin/activate"
