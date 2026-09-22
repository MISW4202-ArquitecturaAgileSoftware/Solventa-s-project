# Gestión Cotizador

Worker del experimento de seguridad. Consume `sol:cotizador`, calcula una prima
determinista y responde en `resp:{correlation_id}`. No expone HTTP ni publica
auditoría de pólizas. La autenticación, autorización y OTP pertenecen a los
componentes anteriores al encolado.

Adaptado de `seguridad`, commit `39d405f`, sobre la base `security`. La lógica
actuarial conserva el comportamiento del cotizador anterior; este servicio usa
los contratos del experimento de seguridad, sin votación ni inyección de fallos.

## Contrato

La solicitud contiene `correlation_id`, `tipo`, `version`, `emitido_en`,
`actor {employee_id, session_id, rol}`, `operacion`, `parametros` y
`fecha_calculo`. La única operación admitida es `cotizar`.

Los parámetros incluyen producto, moneda, suma asegurada como cadena decimal,
plazo, canal, datos del asegurado y consentimiento. El cálculo utiliza Decimal,
el tarifario versionado y la fecha recibida; no consulta el reloj para la edad.

La respuesta contiene la misma correlación, `tipo: operacion.resuelta`,
`servicio: gestion-cotizador`, `estado: OK|ERROR`, `codigo: OK|VALIDACION|INTERNO`,
`duracion_ms`, `resultado` y `error`. Un resultado correcto contiene los bloques
`cotizacion` y `explicacion`.

```text
XREADGROUP sol:cotizador
  → validar y calcular
  → LPUSH resp:{correlation_id} + EXPIRE
  → XACK
```

## Configuración

| Variable | Valor predeterminado |
|---|---|
| `REDIS_URL` | Obligatoria |
| `STREAM_COTIZADOR` | `sol:cotizador` |
| `PREFIJO_RESPUESTAS` | `resp` |
| `TTL_RESPUESTAS_S` | `60` |
| `TARIFARIO_VERSION` | `2026.02` |
| `GRUPO` | `gestion-cotizador` |
| `CONSUMIDOR` | Nombre del contenedor |
| `BLOCK_MS` | `1000` |
| `LOG_LEVEL` | `INFO` |

## Ejecutar desde la raíz del repositorio

```bash
docker compose --env-file example.security.env config --quiet
docker compose --env-file example.security.env up -d --build --wait redis gestion-cotizador
```

Se usa el proyecto `solventa-security` y la red interna `data-negocio`, sin
puertos publicados. La imagen ejecuta Python 3.14.6 con usuario sin privilegios.
El aislamiento de red no sustituye los permisos por servicio sobre Redis; el
worker recibe una identidad que debe venir del flujo autorizado.

## Prueba automática con Redis real

Después del arranque anterior:

```bash
docker compose --env-file example.security.env exec -T gestion-cotizador python - \
  < services/gestion-cotizador/scripts/verificar_redis.py
```

La prueba espera a que exista el grupo, envía cuatro solicitudes y verifica:

- Dos cálculos iguales con correlaciones distintas: prima mensual `90348.41`
  y anual `1084180.92` para el ejemplo canónico.
- Rechazo de una operación de pólizas y de un importe fuera de rango.
- Correlación, TTL de respuestas y confirmación de cada mensaje.

La prueba simula al productor y al receptor de respuestas. No necesita Gateway,
Validación, OTP ni interacción humana. Utilizar un despliegue de prueba; solo
retira sus propias entradas de solicitudes, sin vaciar Redis.

## Pruebas locales

Con un entorno virtual Python 3.14 activo, desde la raíz:

```bash
python -m pip install -r services/gestion-cotizador/requirements-dev.txt
python -m pytest services/gestion-cotizador/tests
```

El paquete tiene contratos, configuración, errores, cálculo y consumo locales.
Las pruebas usan nombres propios para coexistir con el cotizador anterior.

## Límites conservados de la referencia

El grupo se crea por primera vez en `$`: los productores deben esperar su
creación antes de enviar solicitudes. Un grupo existente conserva su posición.
El consumidor lee mensajes nuevos; deja los mensajes corruptos pendientes y
continúa con los siguientes, pero no implementa recuperación de pendientes.
Tampoco garantiza procesamiento exactamente una vez ante fallos entre la
publicación de la respuesta y su confirmación. Estas mejoras quedan separadas
de la adaptación actual.
