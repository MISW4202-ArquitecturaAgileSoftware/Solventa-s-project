# Guía de cambios por servicio — Propuesta A

Este documento resume la versión final de la Propuesta A para facilitar la
revisión, el mantenimiento y la explicación del experimento. La bitácora y la
justificación detallada permanecen en [PROPUESTA-A.md](PROPUESTA-A.md).

## Objetivo general

Se redujo cada servicio a las responsabilidades necesarias para evaluar la
comunicación asíncrona y la votación. Cada servicio quedó autocontenido: puede
construirse, probarse y modificarse desde su propia carpeta, aunque algunos
contratos y utilidades pequeñas estén repetidos.

## Flujo actual

```text
Cliente
  │ HTTP
  ▼
API Gateway
  │ HTTP
  ▼
Votación ───── reporte HTTP en segundo plano ────► Gestión de Errores
  │                                                   │
  │ solicitud por Redis Streams                       └─ evidencia JSONL
  ▼
Cotizadores A, B y C
  │ respuestas por Redis
  └──────────────────────────────► Votación
```

| Servicio | Responsabilidad actual | No debe hacer |
|---|---|---|
| API Gateway | Recibir, identificar y reenviar la solicitud | Calcular, votar o conocer las réplicas |
| Votación | Coordinar las réplicas, comparar y decidir por mayoría | Calcular la prima o decidir si un valor es razonable |
| Cotizador | Consumir, calcular y responder | Votar, exponer HTTP o ocultar su propio fallo |
| Gestión de Errores | Persistir y consultar evidencia | Participar en la decisión o añadir otra cola |

## 1. API Gateway

### Qué se conservó

- Un único endpoint: `POST /v1/cotizaciones`.
- Validación de la presencia de `request_id`.
- Creación de un `correlation_id` para rastrear el recorrido interno.
- Reenvío HTTP al servicio configurado y propagación de su respuesta.
- Timeout y errores diferenciados de conexión, espera y respuesta inválida.
- Logging JSON con niveles `INFO`, `WARNING` y `ERROR`.

### Qué se cambió o eliminó

- La URL dejó de llamarse específicamente “Votación” y pasó a ser
  `QUOTATION_SERVICE_URL`; el gateway es indiferente a la implementación que
  existe detrás.
- Se retiraron identificación de socios, rate limiting y filtrado del consenso.
- Se eliminaron `/health`, `/ready`, el WSGI separado y módulos auxiliares que
  dividían un flujo pequeño.
- El código principal quedó concentrado en `app.py` y
  `structured_logging.py`.

### Motivo

El gateway debe ser una entrada estable para todas las variantes del
experimento. Si aplicara límites, cálculo o reglas de votación, introduciría
errores y latencia que no pertenecen a las tácticas evaluadas.

## 2. Votación

### Qué se conservó

- Publicación de solicitudes para los tres cotizadores mediante Redis.
- Recolección de respuestas hasta completar las tres o alcanzar el límite.
- Mayoría de dos respuestas idénticas entre tres réplicas distintas.
- Reporte de divergencias, falta de quórum y réplicas sin respuesta.
- Fábrica de aplicación para inyectar dobles de Redis y del reportero durante
  las pruebas.

### Qué se corrigió

- Las respuestas se deduplican por `cotizador_id`.
- Se ignoran respuestas pertenecientes a otro `correlation_id`.
- Se compara el resultado funcional completo, no solo la prima ni un hash.
- Una sola respuesta nunca se entrega al cliente: sin dos valores iguales se
  responde `503`; si nadie responde antes del límite, se responde `504`.
- El incidente enviado contiene el resultado completo o el error de cada
  réplica.

### Qué se eliminó

- Fórmula de cálculo, tarifarios y validación de reglas del negocio.
- `hashing.py`, `validacion_resultado.py`, métricas y endpoints de salud.
- La carpeta interna `common` y el WSGI intermedio.
- Errores, contratos y configuración que no usa la votación.

### Motivo

Votación no determina cuál valor parece correcto; únicamente detecta igualdad
y selecciona el valor respaldado por al menos dos réplicas. Esta separación
permite observar si la táctica enmascara el fallo de un cotizador.

## 3. Cotizador

### Qué se conservó

- Un worker que consume solicitudes desde Redis y publica respuestas.
- Cálculo determinista con `Decimal` y tarifarios versionados.
- Validación de los datos requeridos para poder calcular.
- Los modos de inyección de fallos configurados mediante `FAULT_MODE`.
- Apagado ordenado del worker.

### Qué se cambió o eliminó

- Contratos, tarifario, pricing, errores y logging pasaron a módulos directos
  del paquete; se eliminó la carpeta `common`.
- Se retiraron contratos HTTP, tipos de consenso, incidentes e identificadores
  que el worker no utiliza.
- Se eliminó `pricing.validar()`: el cotizador no debe bloquear un resultado
  alterado deliberadamente, porque Votación necesita recibirlo para detectarlo.
- Se eliminaron `health.py`, el latido en Redis y el healthcheck Docker.
- El servicio no expone Flask ni ningún endpoint HTTP.

### Motivo

Cada réplica debe limitarse a calcular y responder. Los modos de fallo son parte
del experimento; ocultarlos dentro del cotizador impediría medir la detección y
el enmascaramiento realizados por Votación.

## 4. Gestión de Errores

### Qué se conservó

- `POST /v1/incidentes` para recibir y persistir evidencia.
- `GET /v1/incidentes` para consultar incidentes, con filtro por
  `correlation_id`.
- `GET /v1/metricas` para contar incidentes por tipo y réplica divergente.
- Persistencia JSONL en un volumen Docker.

### Qué se cambió o eliminó

- La escritura ahora es síncrona: primero agrega la línea al JSONL y después
  responde `201 Created`.
- Se eliminó la segunda cola interna, `escritor.py`, `atexit`, la capacidad de
  cola y los contadores de elementos pendientes o rechazados.
- Se eliminaron `/health`, `/ready`, el healthcheck y el WSGI intermedio.
- Se retiró la carpeta `common` y todos los contratos ajenos a incidentes.
- La evidencia guarda la respuesta funcional completa de cada cotizador o su
  error; ya no guarda hashes ni solamente la prima mensual.

### Motivo

Votación ya hace el reporte en segundo plano, fuera del tiempo de respuesta al
cliente. Una segunda capa asíncrona aumentaba la complejidad y podía confirmar
un incidente antes de persistirlo. Con la escritura directa, recibir `201`
significa que la evidencia ya quedó almacenada.

## 5. Cambios transversales

- Se eliminó la dependencia compartida `libs/solventa-common`.
- Cada servicio tiene sus propios requisitos, pruebas, README, Dockerfile y
  `.dockerignore`.
- Los contextos de construcción Docker se limitan a la carpeta de cada
  servicio.
- El generador de carga conserva un oráculo local para comprobar la prima
  esperada sin importar código de los servicios.
- La evidencia y los ejemplos documentales se alinearon con el resultado
  funcional completo.

## 6. Comportamientos que deben conservarse

1. Sin fallos, A, B y C producen el mismo resultado y Votación responde `200`.
2. Con una réplica divergente, las otras dos forman mayoría, el cliente recibe
   el resultado correcto y se registra el incidente.
3. Con una sola respuesta disponible, no se entrega ninguna cotización.
4. Gestión de Errores no interviene en el cálculo ni en la votación.
5. API Gateway no cambia su lógica entre la variante base y la variante con
   votación; únicamente cambia `QUOTATION_SERVICE_URL`.

## 7. Validación final registrada

- 149 pruebas aprobadas en el conjunto completo.
- Docker Compose validado y servicios reconstruidos.
- Flujo sin fallos verificado.
- Flujo con `FAULT_B=premium_offset` verificado: A y C formaron mayoría, B fue
  identificado como divergente y el cliente recibió la prima correcta.
- El incidente persistido conservó las respuestas completas de A, B y C.
- Después de la prueba, B fue restaurado a `FAULT_MODE=none`.

## 8. Commits de referencia

| Commit | Cambio principal |
|---|---|
| `7f9ea25` | Servicios autocontenidos |
| `7787e93` | Simplificación del API Gateway |
| `ad12b97` | Simplificación y corrección de Votación |
| `e5fc903` | Simplificación del Cotizador |
| `a094ce4` | Simplificación de Gestión de Errores |

