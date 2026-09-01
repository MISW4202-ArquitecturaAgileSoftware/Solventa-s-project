#!/usr/bin/env bash
# Publica una solicitud en el stream, como haría Votación, y devuelve el
# correlation_id. Sirve para probar los cotizadores antes de que exista F5.
#
#   ./scripts/api-calls/publicar-solicitud.sh [ruta-solicitud.json]
#
# Solo usa la biblioteca estándar: no requiere el venv del proyecto.
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"

SOLICITUD="${1:-docs/ejemplos/solicitud.json}"
# Fecha de cálculo congelada: la normaliza Votación, no las réplicas. Fijarla
# hace que el resultado esperado (90348.41) sea reproducible.
FECHA_CALCULO="${FECHA_CALCULO:-2026-08-31}"
TARIFARIO_VERSION="${TARIFARIO_VERSION:-2026.02}"

SOBRE="$(python - "$SOLICITUD" "$FECHA_CALCULO" "$TARIFARIO_VERSION" <<'PY'
import json, sys, uuid
from datetime import UTC, datetime

ruta, fecha_calculo, version = sys.argv[1:4]
with open(ruta, encoding="utf-8") as f:
    payload = json.load(f)

sobre = {
    "correlation_id": str(uuid.uuid7()),
    "tipo": "cotizacion.solicitada",
    "version": "1",
    "emitido_en": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
    "fecha_calculo": fecha_calculo,
    "tarifario_version": version,
    "payload": payload,
}
print(json.dumps(sobre, ensure_ascii=False, separators=(",", ":")))
PY
)"

CID="$(printf '%s' "$SOBRE" | python -c 'import json,sys; print(json.load(sys.stdin)["correlation_id"])')"

docker compose exec -T redis redis-cli XADD cot:req '*' data "$SOBRE" > /dev/null
echo "$CID"
