#!/usr/bin/env bash
# Deja el host y el stack listos para el experimento. Encadena .env, venv,
# imágenes, `up` y un POST de humo al gateway.
#
#   ./scripts/preparar.sh
#   ./scripts/preparar.sh --sin-build   # reutiliza imágenes ya construidas
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

SIN_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --sin-build) SIN_BUILD=1 ;;
    -h | --help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
    *)
      echo "uso: $0 [--sin-build]" >&2
      exit 1
      ;;
  esac
done

paso() { printf '\n### %s\n' "$*"; }

paso "comprobar herramientas"
command -v docker >/dev/null || {
  echo "falta docker" >&2
  exit 1
}
docker compose version >/dev/null || {
  echo "falta docker compose" >&2
  exit 1
}
command -v python >/dev/null || {
  echo "falta python (se espera 3.14)" >&2
  exit 1
}
command -v curl >/dev/null || {
  echo "falta curl" >&2
  exit 1
}
if ! docker info >/dev/null 2>&1; then
  echo "docker no responde: ¿está el daemon y tu usuario en el grupo docker?" >&2
  exit 1
fi
pyv="$(python -c 'import sys; print("%d.%d" % (sys.version_info.major, sys.version_info.minor))')"
if [[ "$pyv" != "3.14" ]]; then
  echo "aviso: python $pyv en PATH; el proyecto espera 3.14" >&2
fi

paso ".env"
if [[ ! -f .env ]]; then
  cp example.env .env
  echo "creado .env desde example.env"
else
  echo ".env ya existe"
fi

paso "venv y Locust"
./scripts/bootstrap.sh

paso "imágenes Docker"
if [[ "$SIN_BUILD" -eq 1 ]]; then
  echo "omitido (--sin-build)"
else
  # El compose declara build.network: host (pip no resuelve pypi.org en la
  # red por defecto de BuildKit). No se usa `compose build --network`: este
  # Compose no trae esa bandera.
  docker compose build
  echo "imágenes listas"
fi

paso "stack"
./scripts/up.sh

paso "humo POST /v1/cotizaciones"
# shellcheck disable=SC1091
set -a
# shellcheck disable=SC1091
source .env
set +a
PUERTO="${PUERTO_GATEWAY:-8000}"
ok=0
for _ in {1..20}; do
  if cuerpo="$(curl -sf --max-time 5 -XPOST "http://localhost:${PUERTO}/v1/cotizaciones" \
    -H 'content-type: application/json' \
    -d @"$RAIZ/docs/ejemplos/solicitud.json")"; then
    if printf '%s' "$cuerpo" | python -c '
import json, sys
d = json.load(sys.stdin)
raise SystemExit(0 if d.get("estado") == "COTIZADO" else 1)
'; then
      printf '%s' "$cuerpo" | python -c '
import json, sys
d = json.load(sys.stdin)
print("COTIZADO", d["cotizacion"]["prima_mensual"])
'
      ok=1
      break
    fi
  fi
  sleep 1
done
if [[ "$ok" -ne 1 ]]; then
  echo "el gateway no cotizó; ver ./scripts/logs.sh" >&2
  exit 1
fi

echo
echo "listo. el stack está arriba."
echo "experimento rápido:   ./scripts/experiment/correr.sh --rapido --sin-pausa"
echo "experimento oficial:  ./scripts/experiment/correr.sh --sin-pausa"
echo "tableros: http://127.0.0.1:8090  (resultados)  http://127.0.0.1:8089  (Locust)"
