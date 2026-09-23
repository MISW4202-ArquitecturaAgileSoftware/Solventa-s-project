# Auditor

Worker puro (sin Flask ni gunicorn) que detecta a posteriori las consultas
fuera de lo habitual (ASR-31). Cada `PERIODO_AUDITORIA_S` lee el stream
`auditoria` que publica `gestion-polizas`, compara la región de cada consulta
con el historial del empleado e informa las regiones nuevas a Validación
(`POST /v1/anomalias`). Validación decide; el Auditor solo detecta.

Se conecta a `backend` (para llamar a Validación) y a `data-control` (para
leer la cola). No publica puertos ni escribe en ningún stream.

## Ciclo (§5.4)

1. **Pendientes propios** (`XREADGROUP … 0`): eventos entregados antes cuya
   anomalía no se pudo informar porque Validación no respondió. `>` no los
   vuelve a entregar nunca; sin este paso no se reintentarían.
2. **Eventos nuevos** (`XREADGROUP … >`, sin bloquear, `COUNT TAMANO_LOTE`),
   solo si los pendientes se resolvieron.
3. Por cada evento:
   - sin `recurso.region` (póliza inexistente) → se ignora;
   - región habitual → `conteo += 1`;
   - región nueva → `POST validacion/v1/anomalias`. Con `ALERTAR` la región se
     incorpora al historial; con `REVOCAR` no, así que cada consulta extra del
     atacante vuelve a informarse y Reacción absorbe el duplicado.
4. `XACK`. Un lote lleno repite el ciclo sin dormir; si no, se duerme el periodo.

Un solo hilo: los ciclos no se solapan por construcción. Log por ciclo:
`ciclo_terminado {eventos, anomalias, duracion_ms}`. Por anomalía:
`anomalia_informada {employee_id, region, decision, latencia_deteccion_ms}`.

### Fallos

- **Validación caída, timeout o 5xx** (transitorio): el lote se corta en ese
  evento y lo demás queda pendiente para el ciclo siguiente. Mientras los
  pendientes sigan fallando no se leen eventos nuevos: un ciclo con Validación
  caída cuesta un timeout, no uno por evento.
- **404 o 422 de Validación** (definitivo, p. ej. empleado desconocido): se
  registra `anomalia_no_informable` y se confirma; reintentar no lo arreglaría.
- **Mensaje corrupto** (JSON inválido, campos ausentes, o recortado por
  `MAXLEN` mientras estaba pendiente): `mensaje_no_procesable` y se confirma,
  para no bloquear la relectura de pendientes.

### Decisiones

- El consumer group se crea en `0`, no en `$`: un detector no debe perder
  eventos publicados antes de su primer arranque.
- El consumidor tiene nombre fijo (`auditor-1`), no el hostname: los
  pendientes pertenecen al consumidor y quedarían huérfanos al recrear el
  contenedor.
- Actualizar el historial y confirmar el evento no son atómicos: si el
  proceso muere entre ambos, al reprocesar la observación se cuenta dos veces.
  Solo afecta a `conteo`, nunca a si una región es habitual.

## Configuración

`REDIS_URL` y `URL_VALIDACION` (obligatorias), `STREAM_AUDITORIA`
(`auditoria`), `GRUPO` (`auditor`), `CONSUMIDOR` (`auditor-1`),
`PERIODO_AUDITORIA_S` (`5`, admite fracciones), `TAMANO_LOTE` (`100`),
`TIMEOUT_HTTP_MS` (`2000`), `RUTA_DB` (`/data/auditor.db`), `LOG_LEVEL`.

## Datos

`historial(employee_id, region, conteo, primera_vez, ultima_vez)`, sembrado
con la columna "Historial" de §2.2 si la base está vacía. El historial no es
el alcance autorizado: `E-ASM-*` tiene `[norte, centro]` autorizado en
Validación pero solo `[norte]` de historial, por eso su primera consulta a
`centro` es inusual (`ALERTAR`) y no fuera de alcance.

## Desarrollo

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python -m pytest -q tests
# Además, contra un Redis real (usa y vacía la base 15):
REDIS_URL_PRUEBAS=redis://localhost:6379/15 PYTHONPATH=src python -m pytest -q -m integracion tests
docker build -t solventa/auditor:dev .
```
