# Validación (incluye Reacción)

Autoriza cada operación contra `permisos_rol`, detecta la elevación de
privilegios comparando el rol declarado con `autorizaciones.ultimo_rol_observado`
y retiene la operación con un OTP de un solo intento (ASR-23). Es el único
servicio que escribe en `sol:polizas` y `sol:cotizador`; la garantía la da la
red, no la disciplina del código. También decide sobre las anomalías que
informa el Auditor (ASR-31) y publica los eventos de `seguridad`.

**Reacción vive dentro de este contenedor**, como fija la vista de despliegue:
un hilo (`reaccion.py`) consume el stream `seguridad`, revoca la sesión y
bloquea al empleado en Autenticación, y registra la alerta en la tabla
`alertas` con `UNIQUE(session_id, motivo)`. La reacción sigue siendo asíncrona
respecto a la API: la API publica, el hilo consume. Un evento repetido para la
misma sesión y motivo se registra como `alerta_duplicada` y no produce una
segunda acción. Si Autenticación no responde, el evento queda pendiente y se
reintenta en la siguiente vuelta (revocación y bloqueo son idempotentes).

## Endpoints

- `POST /v1/operaciones` — autoriza, retiene con OTP o despacha (§5.1).
  `200` con el resultado del worker; `202 OTP_REQUERIDO` si el rol declarado
  difiere del último observado; `403/409/422/504` según la regla que falle.
- `POST /v1/otp` — resuelve el OTP pendiente de una sesión (§5.2). Código
  correcto: actualiza `ultimo_rol_observado`, despacha la operación retenida y
  responde `200`. Código incorrecto: descarta la operación, publica
  `EventoSeguridad {OTP_FALLIDO, REVOCAR}` y responde `403`.
- `POST /v1/anomalias` — decide si una región inusual es `ALERTAR` (dentro de
  `alcance_autorizado`) o `REVOCAR` (fuera de alcance), y publica el evento
  correspondiente (§5.3). Lo llama el Auditor.
- `GET /v1/alertas` — alertas registradas por Reacción, en orden de llegada,
  con `revocada_en` y `bloqueado_en` cuando la contención se completó.
- `GET /v1/experimento/otp/{session_id}` — el canal OTP simulado. Solo con
  `MODO_EXPERIMENTO=true`.
- `GET /health`.

El `correlation_id` de la petición vive en el cuerpo, no en la cabecera: se
fija como identificador del journey en cuanto se lee, y es el primer campo de
la respuesta en `/v1/operaciones` y `/v1/otp`.

## Configuración

`REDIS_URL`, `STREAM_POLIZAS` (`sol:polizas`), `STREAM_COTIZADOR`
(`sol:cotizador`), `PREFIJO_RESPUESTAS` (`resp`), `STREAM_SEGURIDAD`
(`seguridad`), `STREAM_MAXLEN` (`10000`), `TIMEOUT_RESPUESTA_MS` (`2000`),
`RUTA_DB` (por defecto `/data/validacion.db`), `MODO_EXPERIMENTO`, `LOG_LEVEL`.

Reacción: `URL_AUTENTICACION` (obligatoria), `TIMEOUT_HTTP_MS` (`2000`),
`GRUPO_REACCION` (`reaccion`), `CONSUMIDOR_REACCION` (hostname), `BLOCK_MS`
(`1000`), `REACCION_ACTIVA` (`true`; los tests lo apagan para ejercitar el
consumidor de forma síncrona).

## Datos

Siembra `permisos_rol` (§2.1) y `autorizaciones` (§2.2, 13 empleados) si la
base está vacía. `otp_pendientes` y `alertas` no se siembran: nacen con cada
journey.

## Desarrollo

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python -m pytest -q tests
docker build -t solventa/validacion:dev .
```

Los tests no requieren Redis real ni Autenticación: `tests/fake_redis.py` dobla
las listas y streams que usa la API, y `tests/soporte_validacion.py` aporta el
doble de streams con consumer groups y el doble del cliente de Autenticación
que usa Reacción.
