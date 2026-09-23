# Gestión de Pólizas

Worker puro (sin Flask ni gunicorn) que consume `sol:polizas`, resuelve
`consultar_poliza` y `aprobar_poliza` contra su propio SQLite, responde por
`resp:{correlation_id}` y publica un evento de auditoría por cada operación.

Recibe operaciones autorizadas por Validación; no verifica el rol ni el
alcance del `actor`. Solo se conecta a `data-negocio`, sin puertos publicados.
El aislamiento de red no restringe comandos ni claves: los permisos de Redis
deben proteger quién publica en `sol:polizas`.

## Flujo

1. `XREADGROUP` sobre `sol:polizas` (consumer group `GRUPO`, creado en `$`).
2. Ejecuta la operación sobre SQLite (`operaciones.py`).
3. `LPUSH resp:{correlation_id}` + `EXPIRE TTL_RESPUESTAS_S`, en pipeline.
4. `XADD` a `STREAM_AUDITORIA` con el evento de auditoría — nunca lleva
   `prima_mensual` ni `suma_asegurada`, solo lo necesario para evaluar el acceso.
5. `XACK`.

Un mensaje corrupto (JSON inválido o campo del sobre ausente) se registra y se
deja pendiente: no tumba el worker. No hay recuperación automática de
pendientes. La escritura en SQLite, la respuesta y la auditoría son pasos
separados: este worker no garantiza procesamiento exactamente una vez. El
productor debe esperar a que exista el grupo antes de publicar solicitudes.

## Operaciones

- `consultar_poliza {poliza_id}` → la póliza completa, o `NO_ENCONTRADA`.
- `aprobar_poliza {poliza_id}` → `PENDIENTE → APROBADA` con `aprobada_por` =
  `actor.employee_id`; `NO_ENCONTRADA` si no existe, `ESTADO_INVALIDO` si no
  estaba `PENDIENTE`.
- Operación desconocida o parámetros inválidos → `VALIDACION`. Excepción
  inesperada → `INTERNO`.

## Configuración

`REDIS_URL` (obligatoria), `STREAM_POLIZAS` (`sol:polizas`), `PREFIJO_RESPUESTAS`
(`resp`), `STREAM_AUDITORIA` (`auditoria`), `STREAM_MAXLEN` (`10000`),
`TTL_RESPUESTAS_S` (`60`), `RUTA_DB` (`/data/polizas.db`), `GRUPO`
(`gestion-polizas`), `CONSUMIDOR` (por defecto el hostname del contenedor —
deliberadamente no se fija en el compose para que cada réplica tenga un
identificador propio), `BLOCK_MS` (`1000`), `LOG_LEVEL`.

## Datos

Siembra las 60 pólizas del experimento de seguridad si la base está vacía:
20 por región (`norte`, `sur`, `centro`), `001..010` en `PENDIENTE` y
`011..020` en `EMITIDA`. `suma_asegurada` y `prima_mensual` son cadenas
decimales deterministas derivadas del número de póliza.

## Desarrollo

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python -m pytest -q tests
docker build -t solventa/gestion-polizas:dev .
```
