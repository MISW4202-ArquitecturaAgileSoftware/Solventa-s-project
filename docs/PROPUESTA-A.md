# Propuesta A

Bitácora de las decisiones y cambios realizados sobre la propuesta original del
experimento. Este documento se actualizará junto con cada cambio relevante.

## Objetivo

Mantener una arquitectura experimental sencilla, comprensible y fácil de
modificar. Se prioriza que cada servicio sea autónomo a nivel de desarrollo,
pruebas y construcción Docker, aun cuando esto implique duplicar una cantidad
pequeña de contratos y utilidades.

## Cambios realizados

### 1. Servicios autocontenidos

- Se eliminó la dependencia de código fuente `libs/solventa-common`.
- Cada servicio conserva localmente los contratos y utilidades que necesita.
- El cálculo, tarifario y sus pruebas quedaron bajo la responsabilidad del
  servicio Cotizador.
- El generador del experimento conserva un oráculo local para verificar la prima
  esperada sin importar código de otro servicio.

### 2. Construcción Docker aislada

- Cada Dockerfile usa la carpeta del servicio como contexto de construcción.
- Ninguna imagen necesita leer archivos de otra carpeta del repositorio.
- Cada servicio incluye su propio `.dockerignore`.

### 3. Desarrollo independiente

Cada servicio incluye:

- `requirements.txt` para ejecución.
- `requirements-dev.txt` para pruebas locales.
- `README.md` con los comandos básicos.
- Su código fuente y su suite de pruebas.

### 4. Validación

- 193 pruebas aprobadas.
- Configuración de Docker Compose válida.
- Imágenes de API Gateway, Voting, Cotizador y Gestor de Errores construidas
  usando contextos aislados.
- Stack completo levantado con todos los contenedores saludables.
- Cotización extremo a extremo verificada con prima mensual `90348.41`.

## Estado actual

La autonomía de los servicios conserva el comportamiento funcional de la
propuesta original. Los siguientes cambios de la Propuesta A se documentarán en
nuevas secciones y commits separados.

### 5. API Gateway mínimo

#### Propósito del refactor

La implementación original mezclaba responsabilidades propias de un gateway de
producción con las necesarias para este experimento. Eso aumentaba la cantidad
de módulos, configuraciones y caminos de error que podían afectar las mediciones
sin formar parte de las tácticas evaluadas. El servicio se redujo para que su
participación sea estable, visible y fácil de explicar.

#### Responsabilidades conservadas

El gateway conserva únicamente lo necesario para conectar al cliente con el
sistema experimental:

- recibir `POST /v1/cotizaciones`;
- exigir un `request_id` en el cuerpo de la solicitud;
- generar un `correlation_id` UUIDv7 para rastrear todo el recorrido;
- reenviar a una URL de cotización genérica con timeout;
- propagar el cuerpo y el estado HTTP del servicio interno;
- devolver errores diferenciados para timeout, conexión y respuesta inválida;
- registrar tiempo, estado e identificadores en formato JSON, usando `INFO`,
  `WARNING` o `ERROR` según el resultado.

El `request_id` identifica la solicitud desde el punto de vista del cliente. El
`correlation_id` lo crea el gateway y permite relacionar esa solicitud con la
votación, los mensajes de Redis y las respuestas de los tres cotizadores.

La variable `QUOTATION_SERVICE_URL` reemplaza el nombre específico de Votación.
Así el gateway solo conoce el contrato HTTP del siguiente componente y puede
usarse tanto con una implementación base como con una implementación que tenga
asincronía y votación.

#### Responsabilidades retiradas y justificación

- **Identificación de socios:** `X-Partner-Id` no es una entrada ni una métrica
  del experimento. Mantenerlo agregaba rechazos ajenos a las fallas inyectadas.
- **Límite de tasa:** podía producir respuestas `429` y alterar artificialmente
  el número de solicitudes exitosas durante las pruebas de carga.
- **Filtrado del consenso:** el gateway ahora es transparente. La decisión de
  exponer información experimental permanece en el servicio que genera el
  consenso mediante su propia configuración.
- **Readiness y health endpoint:** ningún componente dependía de ellos y no
  aportaban datos a las métricas evaluadas. También acoplaban el estado del
  gateway al estado de Votación.
- **Cliente llamado `cliente_votacion`:** fue reemplazado por una llamada HTTP
  genérica para evitar que el gateway conozca la táctica instalada detrás.
- **Rate limiter, app factory, WSGI separado y utilidades comunes:** se retiraron
  porque dividían un flujo pequeño entre varios archivos sin aportar una
  variación experimental.

El resultado pasa de varios módulos especializados a dos archivos principales:
`app.py`, con el flujo HTTP, y `structured_logging.py`, con la salida de logs.
Las variables requeridas quedan reducidas a `QUOTATION_SERVICE_URL`,
`UPSTREAM_TIMEOUT_MS` y `LOG_LEVEL`.

#### Alcance de la decisión

Esta simplificación es apropiada para el experimento, pero no pretende definir
un gateway completo de producción. Autenticación, autorización, rate limiting y
políticas de exposición podrían incorporarse posteriormente si fueran parte de
los requisitos del sistema real. No se incluyen ahora porque añadirían variables
que dificultan atribuir los resultados a la asincronía y a la votación.

#### Validación

- 11 pruebas del API Gateway aprobadas.
- 182 pruebas del repositorio aprobadas.
- Imagen reconstruida y contenedor en ejecución.
- Cotización extremo a extremo con prima mensual `90348.41`.
- Corrida corta de 10 solicitudes: 10 respuestas exitosas, 0 primas erróneas y
  P95 de `10.9 ms`.

### 6. Servicio de Votación seguro y reducido

#### Propósito del refactor

Votación contiene la táctica central del experimento, por lo que no puede ser
tan pequeño como el API Gateway. La revisión separó la complejidad necesaria
—publicar, recolectar y decidir— de lógica de cálculo e infraestructura que no
le correspondían.

#### Correcciones de la decisión

- Las respuestas se deduplican por `cotizador_id`; una réplica no puede formar
  quórum enviando dos veces el mismo resultado.
- Se descartan respuestas cuyo `correlation_id` no corresponde al recorrido
  actual.
- Votación compara directamente el resultado funcional completo —cotización,
  versión del tarifario y explicación—; no calcula ni utiliza hashes.
- Sin dos respuestas válidas coincidentes no se entrega una cotización. El
  anterior estado `COTIZADO_DEGRADADO`, basado en una sola respuesta, se
  reemplazó por `RECHAZADO` porque no existía una segunda opinión que confirmara
  el valor.

Estas reglas protegen la propiedad esencial de una votación: el quórum debe
estar formado por réplicas distintas que entregaron el mismo valor.

#### Respuestas HTTP

| Situación | HTTP | Decisión |
|---|:---:|---|
| Resultado completo idéntico en 2 o 3 réplicas | `200` | Se entrega el resultado mayoritario |
| Respuestas recibidas, pero ninguna alcanza el quórum | `503` | Se rechaza por falta de consenso |
| Una sola réplica responde | `503` | Se rechaza porque no existe segunda opinión |
| Ninguna réplica responde antes del límite | `504` | Se informa timeout del recorrido |
| Excepción inesperada en Votación | `500` | Error interno |

#### Responsabilidades retiradas

- Se retiraron la fórmula de prima, las tablas del tarifario y todas las reglas
  de validez del negocio. Votación no decide si un valor es razonable: solo lo
  compara con las otras respuestas.
- Se eliminaron `hashing.py` y `validacion_resultado.py`. Los contratos son
  estructuras inmutables y se comparan directamente, sin introducir una
  representación intermedia.
- `TARIFARIO_VERSION` dejó de ser configuración de Votación. Cada Cotizador usa
  su propia versión al realizar el cálculo.
- Se eliminaron `/health`, `/ready` y los contadores de `/v1/metricas`, porque no
  son entradas ni evidencias necesarias del experimento. Los resultados del
  consenso viajan en la respuesta y los incidentes se almacenan en Gestión de
  Errores.
- Se eliminó el archivo WSGI intermedio; Gunicorn invoca directamente la fábrica
  de la aplicación.
- Se retiraron errores heredados de otros servicios que Votación nunca usaba.
- Se eliminó la carpeta interna `common`. Sus contratos, errores, IDs y
  logging estructurado pertenecen directamente a Votación y ahora están en la
  raíz del paquete, evitando un nivel de navegación que no representaba una
  frontera arquitectónica real.

La fábrica de aplicación sí se conserva. A diferencia del gateway, aquí permite
inyectar un doble de Redis y un reportero controlado en las pruebas sin levantar
infraestructura externa.

Esta versión hace explícita la premisa de la táctica: como máximo puede fallar
una réplica. Si dos cotizadores coinciden en un valor incorrecto, ese valor
formará mayoría; Votación no conoce el cálculo para refutarla.

#### Validación

- 35 pruebas del servicio de Votación.
- 181 pruebas aprobadas en el repositorio completo.
- Nuevas pruebas para duplicados, correlación ajena, comparación del resultado
  completo y contrato HTTP.
- Sin fallas: respuesta `200`, acuerdo 3 de 3 y prima mensual `90348.41`.
- Con `FAULT_B=premium_offset`: respuesta `200`, acuerdo 2 de 3, réplica B
  detectada como divergente y prima correcta `90348.41`.
- Con B y C en modo `crash`: respuesta `503`; el único valor disponible no se
  entrega por falta de quórum.
- Tras restaurar las réplicas, el sistema vuelve a acuerdo 3 de 3.

### 7. Cotizador reducido a un worker de cálculo

#### Responsabilidad conservada

Cada réplica mantiene un único recorrido: consume una solicitud desde Redis,
calcula con su tarifario, aplica el modo de fallo configurado y publica la
respuesta. Continúan siendo necesarios el cálculo determinista con `Decimal`,
las tablas versionadas, los nueve modos —incluido `none`— y el apagado ordenado.

#### Código retirado

- Se eliminó la carpeta `common`; contratos, errores, tarifario, pricing y
  logging estructurado son módulos directos del Cotizador.
- Se retiraron IDs, errores HTTP, estados de la cotización, incidentes y tipos
  de consenso. El worker recibe el `correlation_id` y no ofrece una API HTTP.
- Se eliminó `pricing.validar()`. El Cotizador valida la solicitud y los datos
  necesarios para calcular, pero no descarta su propio resultado: hacerlo
  ocultaría los fallos que el experimento debe entregar a Votación.
- Se eliminó `health.py`, el latido en Redis, su configuración y el healthcheck
  de la imagen. Las corridas comienzan después de que `docker compose up` haya
  levantado los procesos del stack controlado.
- El contrato implementa solo las direcciones usadas: recibe y deserializa el
  sobre de solicitud; construye y serializa el sobre de respuesta.

Los modos de fallo se mantienen porque forman parte de las corridas del
experimento. Votación no conoce su implementación y compara el resultado
funcional completo producido por cada réplica.

#### Validación

- 87 pruebas del Cotizador y 154 pruebas del repositorio aprobadas.
- Imagen reconstruida; las réplicas A, B y C quedaron en ejecución.
- Sin fallas: acuerdo 3 de 3 y prima mensual `90348.41`.
- Con `FAULT_B=factor_skip`: acuerdo 2 de 3, B detectado como divergente y el
  cliente recibió el resultado sano.
- B fue restaurado a `FAULT_MODE=none` después de la comprobación.

### 8. Gestión de Errores como registro mínimo de evidencia

#### Flujo simplificado

Votación ya realiza el reporte en un hilo fuera de la respuesta al cliente.
Por eso se eliminó la segunda cola interna de Gestión de Errores: el endpoint
valida, anexa una línea al JSONL y responde `201 Created`. Una confirmación
significa ahora que la evidencia ya está persistida, no solo aceptada en memoria.

#### Código y contratos retirados

- Se eliminaron `escritor.py`, su cola, capacidad, contadores de pendientes,
  apagado con `atexit` y pruebas asociadas.
- Se retiraron `/health`, `/ready`, el healthcheck de Docker y el WSGI
  intermedio. El stack del experimento se levanta de forma controlada.
- Se eliminó la carpeta `common` y los contratos heredados de solicitudes,
  cotizaciones y sobres Redis.
- Solo se conservan los tres tipos que Votación puede emitir: divergencia,
  falta de quórum y réplica sin respuesta.

La evidencia dejó de guardar hashes o únicamente la prima. Cada valor recibido
contiene el resultado funcional completo —o el error— de la réplica, de modo
que el incidente permite auditar exactamente qué campo fue diferente.

#### Interfaz conservada

- `POST /v1/incidentes`: persiste y responde `201`.
- `GET /v1/incidentes`: consulta la evidencia.
- `GET /v1/metricas`: calcula el numerador de detección sobre el JSONL.

#### Validación

- 16 pruebas de Gestión de Errores y 149 pruebas del conjunto completo
  aprobadas.
- Contrato de Votación actualizado para reportar resultados completos.
- Configuración de Compose y compilación de ambos servicios verificadas.
- Prueba integrada con `FAULT_B=premium_offset`: A y C formaron mayoría, el
  cliente recibió la prima correcta y B quedó registrado como divergente.
- El incidente persistido conservó las respuestas funcionales completas de A,
  B y C; después de la prueba, B fue restaurado a `FAULT_MODE=none`.
