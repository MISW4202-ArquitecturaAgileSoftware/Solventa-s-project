# Auditor

Worker puro (sin Flask ni gunicorn) que detecta a posteriori las consultas
fuera del alcance habitual de un empleado (ASR-31). Cada `PERIODO_AUDITORIA_S`
lee el stream `auditoria`, compara la región consultada contra el historial
del empleado y, si es nueva, pregunta a Validación (`POST /v1/anomalias`) si
es una anomalía a contener o un uso legítimo pero inusual.

## Ciclo

```
loop hasta SIGTERM:
  releer pendientes propios (XREADGROUP id "0") y luego los nuevos (">"), sin bloquear
  por evento:
    sin región            -> XACK, sigue
    región ya habitual    -> incrementa el conteo, XACK
    región nueva          -> pregunta a Validación
                              ALERTAR -> incorpora la región al historial
                              REVOCAR -> no la incorpora
                              XACK
    fallo transitorio de Validación -> no XACK; se reintenta en el ciclo siguiente
  lote lleno (== LOTE) -> repite sin dormir; si no, duerme PERIODO_AUDITORIA_S
```

Un solo hilo: los ciclos no se solapan por construcción.

## Configuración

- `REDIS_URL`, `URL_VALIDACION` (obligatorias).
- `STREAM_AUDITORIA` (`auditoria`), `PERIODO_AUDITORIA_S` (`5`), `LOTE` (`100`),
  `TIMEOUT_HTTP_MS` (`2000`), `RUTA_DB` (`/data/auditor.db`), `GRUPO`
  (`auditor`), `CONSUMIDOR` (hostname del contenedor), `LOG_LEVEL`.

## Datos

Siembra `historial(employee_id, region)` con los datos de
`PLAN-IMPLEMENTACION.md` §2.2 si la base está vacía: `E-ASN-01..10` y
`E-ASM-01..02` con `norte`; `E-SUP-01` con `norte`, `sur` y `centro`.

## Desarrollo

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python -m pytest -q tests
docker build -t solventa/auditor:dev .
```
