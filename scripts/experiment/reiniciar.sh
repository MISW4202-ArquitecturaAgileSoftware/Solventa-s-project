#!/usr/bin/env bash
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"
[[ -f .env ]] || { echo "falta .env: copiar desde example.env" >&2; exit 1; }

# Reinicia el stack con semillas limpias: cada repetición del experimento
# necesita empleados sin revocar ni bloquear, y solo un stack nuevo lo
# garantiza. PERIODO_AUDITORIA_S puede venir fijado en el entorno del shell
# (p. ej. `PERIODO_AUDITORIA_S=2 scripts/experiment/reiniciar.sh`): Compose le
# da prioridad sobre el valor de .env, así que gobierna la ventana de
# exposición de esta corrida sin tocar el archivo.
docker compose down -v --remove-orphans
docker compose up -d --wait
