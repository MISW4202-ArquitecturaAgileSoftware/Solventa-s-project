# Plan de implementación — Monorepo Solventa

Plan operativo para construir el monorepo de microservicios que materializa el
experimento de **detección** (ASR-11) y **enmascaramiento** (ASR-12) de un
cálculo erróneo de prima, según el diagrama de despliegue `image.png`.

## 0. Cómo se usa este plan

**Regla dura: un servicio a la vez.** No se inicia una fase sin que la validación
de la fase anterior esté en verde. Cada fase declara *objetivo*, *pasos*,
*comando de validación* y *resultado esperado*; si el resultado observado no
coincide con el esperado, se corrige antes de avanzar.

Orden de construcción (dictado por las dependencias del diagrama):

```
F0 andamiaje  →  F1 contratos locales →  F2 queue-service  →  F3 cotizador
              →  F4 gestion-errores  →  F5 votacion       →  F6 api-gateway
              →  F7 experimento
```

`gestion-errores` va antes que `votacion` porque Votación depende de él
(flecha `Votacion → GestorErrores` en el diagrama). `api-gateway` va al final
porque solo enruta: no puede probarse sin un journey completo detrás.

### Decisiones ya cerradas

| Decisión | Valor |
|---|---|
| Semántica de la cola | **Fan-out**: cada solicitud llega a A, B y C |
| Diversidad de réplicas | **Idénticas**, una sola imagen, fallo por `FAULT_MODE` |
| Layout | `services/<servicio>/`, `requirements.txt` por servicio |
| Autonomía | Cada servicio contiene sus contratos y utilidades; no existe una librería compartida |
| Compose | **Un `docker-compose.yaml` por servicio**, unidos por `include:` en la raíz |
| Cola | `redis:8.10-alpine` (Streams para la ida, listas para la vuelta) |
| Runtime | Python 3.14.6 (pyenv) |
| `cotizador` | **Worker puro**, sin Flask ni gunicorn: solo consume de la cola |
| Resto de servicios | Flask (app factory + blueprints) + gunicorn `gthread` |

---

# 1. Contratos

Cada servicio conserva dentro de su propio paquete los contratos que consume o
produce. La duplicación pequeña es deliberada: permite construir, probar y
mantener una carpeta sin depender de código fuente externo. Las pruebas de
contrato verifican la compatibilidad de los mensajes entre servicios.

## 1.1 Identificación de la petición

Toda petición es identificable de extremo a extremo por un `correlation_id`
**UUIDv7** (`uuid.uuid7()`, disponible en Python 3.14). Se elige v7 y no v4
porque es ordenado en el tiempo: los IDs ordenan naturalmente en los logs y en
los Streams de Redis, lo que hace depurable el experimento.

| Identificador | Lo genera | Alcance | Para qué sirve |
|---|---|---|---|
| `request_id` | El cliente, en el cuerpo JSON | La petición del cliente | Trazabilidad del lado del cliente; es obligatorio y se conserva tal cual |
| `correlation_id` | API Gateway (`uuid7`) | El journey completo | Une la solicitud con los 3 cálculos y con el veredicto |
| `cotizador_id` | Cada réplica, de `COTIZADOR_ID` | Una réplica | Identifica quién produjo cada resultado (`A`, `B`, `C`) |
| `resultado_hash` | Cada réplica | Un resultado | Comparación exacta en la votación |

El gateway rechaza las solicitudes sin `request_id`. El `correlation_id` viaja en:

- la cabecera `X-Correlation-Id` de la respuesta,
- el campo `correlation_id` de **todo** mensaje del envelope interno,
- el campo `correlation_id` de **todo** log estructurado,
- el nombre de la lista de respuestas: `cot:resp:{correlation_id}`.

## 1.2 Payload de entrada (el que llega al gateway)

```http
POST /v1/cotizaciones HTTP/1.1
Content-Type: application/json
```

```json
{
  "request_id": "solicitud-ejemplo-001",
  "producto": "vida_hipotecario",
  "moneda": "COP",
  "suma_asegurada": "250000000.00",
  "plazo_meses": 240,
  "canal": "banco_aliado",
  "asegurado": {
    "fecha_nacimiento": "1988-04-17",
    "genero": "F",
    "fumador": false,
    "clase_ocupacional": 2
  },
  "consentimiento_open_finance": true
}
```

| Campo | Tipo | Obligatorio | Regla de validación |
|---|---|:---:|---|
| `producto` | enum | sí | `vida_hipotecario` (único producto en el alcance del experimento) |
| `moneda` | ISO-4217 | sí | `COP` |
| `suma_asegurada` | decimal como **string** | sí | `10_000_000 ≤ x ≤ 2_000_000_000` |
| `plazo_meses` | entero | sí | `12 ≤ x ≤ 360` |
| `canal` | enum | sí | `banco_aliado` \| `retail` \| `directo` |
| `asegurado.fecha_nacimiento` | `YYYY-MM-DD` | sí | edad resultante entre 18 y 75 años |
| `asegurado.genero` | enum | sí | `F` \| `M` \| `X` (no afecta la tarifa; se registra) |
| `asegurado.fumador` | booleano | sí | — |
| `asegurado.clase_ocupacional` | entero | sí | `1..4` |
| `consentimiento_open_finance` | booleano | sí | si es `false`, se cotiza sin señales externas |

> Los montos viajan **como string**, nunca como número JSON. Un `float` de JSON
> no representa exactamente valores monetarios y rompería el determinismo entre
> réplicas, que es justo lo que el experimento mide.

## 1.3 Payload de salida

```http
200 OK
Content-Type: application/json
X-Correlation-Id: 01a05aa8-24a1-753e-b019-a0810d66a3f6
```

```json
{
  "correlation_id": "01a05aa8-24a1-753e-b019-a0810d66a3f6",
  "request_id": "7f3c...",
  "estado": "COTIZADO",
  "emitido_en": "2026-08-31T20:41:07.512Z",
  "cotizacion": {
    "moneda": "COP",
    "suma_asegurada": "250000000.00",
    "prima_mensual": "90348.41",
    "prima_anual": "1084180.92",
    "plazo_meses": 240,
    "vigencia_dias": 15,
    "tarifario_version": "2026.02"
  },
  "explicacion": {
    "edad_calculada": 38,
    "tasa_base_mil": "0.26",
    "factores": {
      "fumador": "1.00",
      "clase_ocupacional": "1.12",
      "plazo": "1.08",
      "canal": "0.95"
    },
    "gasto_administrativo": "0.12",
    "margen": "0.08"
  }
}
```

`estado` toma tres valores: `COTIZADO` (consenso limpio), `COTIZADO_DEGRADADO`
(hubo divergencia o faltaron respuestas, pero se resolvió un valor correcto) y
`RECHAZADO` (no fue posible resolver un valor confiable).

### Bloque de consenso (evidencia del experimento)

```json
"consenso": {
  "estrategia": "quorum_2_de_3",
  "respuestas_recibidas": 3,
  "acuerdo": 2,
  "divergencia_detectada": true,
  "replicas_divergentes": ["B"],
  "latencia_consenso_ms": 41
}
```

Este bloque **solo se incluye si `EXPOSE_CONSENSUS=true`**. ASR-12 exige responder
«sin exponer el error», así que en un despliegue productivo el socio nunca lo ve;
se activa en desarrollo y durante el experimento para poder medir. Con el flag
apagado, la divergencia sigue reportándose íntegra a `gestion-errores`.

### Errores — RFC 9457 (`application/problem+json`)

```json
{
  "type": "https://solventa.co/errors/validacion",
  "title": "Solicitud de cotización inválida",
  "status": 422,
  "detail": "asegurado.clase_ocupacional debe estar entre 1 y 4",
  "instance": "/v1/cotizaciones",
  "correlation_id": "01a05aa8-..."
}
```

| Situación | HTTP | `type` |
|---|:---:|---|
| Falta `request_id` en la entrada al gateway | 400 | `request_id_required` |
| Payload malformado o fuera de rango | 422 | `/errors/validacion` |
| Sin quórum y sin valor confiable | 503 | `/errors/sin-consenso` |
| Timeout del journey | 504 | `/errors/timeout-cotizacion` |

## 1.4 Envelope interno (Redis)

**Solicitud** — `XADD cot:req` (un consumer group por réplica ⇒ fan-out):

```json
{
  "correlation_id": "01a05aa8-...",
  "tipo": "cotizacion.solicitada",
  "version": "1",
  "emitido_en": "2026-08-31T20:41:07.470Z",
  "fecha_calculo": "2026-08-31",
  "tarifario_version": "2026.02",
  "payload": { "...solicitud normalizada..." }
}
```

**Respuesta** — `LPUSH cot:resp:{correlation_id}`:

```json
{
  "correlation_id": "01a05aa8-...",
  "tipo": "cotizacion.calculada",
  "cotizador_id": "B",
  "estado": "OK",
  "resultado_hash": "9f2a...",
  "duracion_ms": 7,
  "resultado": { "...bloques cotizacion y explicacion..." }
}
```

> **Normalización antes del fan-out.** Votación fija `fecha_calculo` y
> `tarifario_version` **una sola vez** y las mete en el mensaje. Si cada réplica
> resolviera la fecha con `date.today()`, una petición a medianoche produciría
> edades distintas y una divergencia falsa. Las réplicas reciben una entrada
> completamente determinada; su única fuente de variación permitida es el fallo
> inyectado.

---

# 2. Mecanismo de cálculo de la cotización

## 2.1 Requisitos de determinismo

La votación solo funciona si dos réplicas sanas producen resultados **idénticos
bit a bit**. Por tanto:

1. Todo el dinero se maneja con `decimal.Decimal`, **nunca** `float`.
2. Redondeo único y explícito al final: `ROUND_HALF_UP` a 2 decimales. Los pasos
   intermedios no se redondean.
3. Las tablas actuariales son constantes versionadas (`tarifario_version`), no
   consultas a base de datos ni a servicios externos.
4. Ninguna entrada implícita: ni `date.today()`, ni `random`, ni variables de
   entorno que alteren el resultado (salvo `FAULT_MODE`, que es el fallo).
5. El orden de las operaciones está fijado por la fórmula, no por iteración
   sobre un diccionario.

## 2.2 Tarifario `2026.02` — producto `vida_hipotecario`

**Tasa base mensual por mil asegurado**, según edad cumplida a `fecha_calculo`:

| Rango de edad | `tasa_base_mil` |
|---|---|
| 18 – 29 | 0.18 |
| 30 – 39 | 0.26 |
| 40 – 49 | 0.45 |
| 50 – 59 | 0.92 |
| 60 – 69 | 1.85 |
| 70 – 75 | 3.40 |

**Factores multiplicativos:**

| Factor | Valores |
|---|---|
| `f_fumador` | no → 1.00 · sí → 1.45 |
| `f_clase_ocupacional` | 1 → 1.00 · 2 → 1.12 · 3 → 1.35 · 4 → 1.80 |
| `f_plazo` | ≤120 m → 1.00 · 121–240 m → 1.08 · >240 m → 1.15 |
| `f_canal` | `banco_aliado` → 0.95 · `retail` → 1.00 · `directo` → 0.97 |

**Constantes:** `gasto_administrativo = 0.12`, `margen = 0.08`.

## 2.3 Fórmula

```
edad          = años cumplidos entre fecha_nacimiento y fecha_calculo

prima_pura    = (suma_asegurada / 1000)
              * tasa_base_mil(edad)
              * f_fumador
              * f_clase_ocupacional
              * f_plazo

prima_mensual = round_half_up(
                    prima_pura * f_canal * (1 + gasto_administrativo) * (1 + margen),
                    2)

prima_anual   = round_half_up(prima_mensual * 12, 2)
```

**Ejemplo canónico** (se usa como test de referencia en toda fase):

```
suma_asegurada = 250000000.00   plazo = 240 m   canal = banco_aliado
edad = 38  ·  no fumador  ·  clase ocupacional 2

prima_pura    = 250000 × 0.26 × 1.00 × 1.12 × 1.08        = 78624.00
prima_mensual = 78624 × 0.95 × 1.12 × 1.08                = 90348.41
prima_anual   = 90348.41 × 12                             = 1084180.92
```

## 2.4 Regla de validez (la que hace posible ASR-11)

Un resultado es **estructuralmente inválido** si:

```
ratio = prima_mensual / suma_asegurada        debe cumplir   0.00005 ≤ ratio ≤ 0.02
prima_mensual > 0
prima_anual == round_half_up(prima_mensual × 12, 2)
tarifario_version == la del mensaje de solicitud
```

Esto da a Votación **dos vías de detección independientes**, y hay que
implementarlas ambas:

- **Detección por rango** (funciona incluso con una sola respuesta): el resultado
  viola una regla de validez.
- **Detección por divergencia** (necesita ≥2 respuestas): los `resultado_hash`
  no coinciden entre réplicas.

## 2.5 Hash del resultado

```
resultado_hash = sha256(json_canonico({
    "prima_mensual", "prima_anual", "tasa_base_mil",
    "factores", "tarifario_version", "edad_calculada"
}))
```

JSON canónico = claves ordenadas, separadores compactos, sin espacios, UTF-8.
El hash **excluye** `cotizador_id`, `duracion_ms` y cualquier marca de tiempo:
esos campos varían por réplica y no son parte del resultado a comparar.

## 2.6 Modos de fallo inyectables (`FAULT_MODE`)

| Valor | Efecto | Qué mecanismo de detección ejercita |
|---|---|---|
| `none` | Cálculo correcto | — (línea base) |
| `premium_offset` | Multiplica la prima final por 1.15 | Divergencia de hash |
| `factor_skip` | Ignora `f_clase_ocupacional` | Divergencia de hash |
| `rate_table_stale` | Usa el tarifario `2025.11` | Divergencia + versión |
| `rounding_drift` | Redondea con `ROUND_DOWN` a 0 decimales | Divergencia de hash |
| `out_of_range` | Devuelve `prima_mensual` × 500 | Regla de rango |
| `silent_zero` | Devuelve `prima_mensual = 0` | Regla de rango |
| `slow` | Duerme 400 ms antes de responder | Quórum parcial por timeout |
| `crash` | No responde (excepción no capturada) | Quórum parcial |

Se activan por variable de entorno y por réplica, sin reconstruir la imagen:
`FAULT_B=premium_offset ./scripts/up.sh`.

---

# 3. Fases de implementación

## F0 · Andamiaje del repositorio

**Objetivo:** que exista la estructura, el tooling y un `compose config` válido
antes de escribir una línea de lógica.

**Estructura objetivo**

```
Solventa-s-project/
├── .gitattributes .gitignore .dockerignore
├── .env example.env                       # únicos archivos de entorno, en la raíz
├── docker-compose.yaml                    # solo include: + redes compartidas
├── pyproject.toml                         # tooling: ruff, mypy, pytest
├── services/
│   ├── api-gateway/{docker-compose.yaml, Dockerfile, requirements.txt, src/, tests/}
│   ├── votacion/{docker-compose.yaml, Dockerfile, requirements.txt, src/, tests/}
│   ├── cotizador/{docker-compose.yaml, Dockerfile, requirements.txt, src/, tests/}  # worker
│   └── gestion-errores/{docker-compose.yaml, Dockerfile, requirements.txt, src/, tests/}
├── queue-service/{docker-compose.yaml, redis.conf}
├── scripts/{up.sh, down.sh, build.sh, logs.sh, test.sh, api-calls/, experiment/}
└── docs/{ASRs-experimento.md, image.png, ejemplos/, adr/}
```

Todos los archivos de Compose se llaman **`docker-compose.yaml`** (no
`compose.yaml`). El de la raíz los agrupa:

```yaml
include:
  - queue-service/docker-compose.yaml
  - services/cotizador/docker-compose.yaml
  - services/gestion-errores/docker-compose.yaml
  - services/votacion/docker-compose.yaml
  - services/api-gateway/docker-compose.yaml
```

Con `include`, las rutas relativas de cada archivo resuelven contra **su propio
directorio**; por eso cada servicio declara `context: .` y puede construirse
usando únicamente los archivos de su carpeta.

**Pasos**

1. `.gitattributes` con `* text=auto eol=lf` (WSL2: evita CRLF en los scripts que
   entran a las imágenes).
2. `.gitignore` (`.venv/`, `__pycache__/`, `.env`, `*.pyc`) y `.dockerignore` en
   la raíz (`.git`, `.venv`, `docs/`, `**/tests`, `**/__pycache__`).
3. `example.env` commiteado + `.env` local, ambos en la raíz, con: `STACK=solventa`,
   `TAG=dev`, `REDIS_URL`, `QUORUM`, `TIMEOUT_CONSENSO_MS`, `EXPOSE_CONSENSUS`,
   `FAULT_A/B/C`.
4. Mover los directorios existentes a `services/`; crear `scripts/` y `docs/`,
   y mover ahí `ASRs-experimento.md` e `image.png`.
5. `docker-compose.yaml` raíz: solo `include:` de los cinco compose y la
   declaración de las redes. Son cinco, no tres:

   | Red | `internal` | Quién se conecta |
   |---|:---:|---|
   | `edge` | no | Solo el API Gateway. Única zona con salida al exterior. |
   | `backend` | sí | Gateway ↔ Votación ↔ GestorErrores. |
   | `data-votacion` | sí | Votación ↔ Redis. |
   | `data-cotizadores` | sí | Cotizadores ↔ Redis. |
   | `ops` | no | Acceso desde el host para operar y medir. |

   La zona de la cola se parte en dos a propósito. Con una sola red compartida,
   los cotizadores podrían alcanzar a Votación por HTTP y nada impediría que
   alguien añadiera después una llamada directa que saltara la cola. Con Redis
   como único servicio presente en ambas, el **único** camino entre Votación y
   las réplicas es la cola, y lo garantiza la red, no la disciplina del equipo.

   `ops` existe porque un servicio conectado solo a redes `internal: true` no
   puede publicar puertos, y sin publicarlos no habría cómo leer `/v1/metricas`
   para medir ASR-11. Los cotizadores nunca se conectan ahí.
6. `scripts/{up,down,build,logs,test}.sh` con `set -euo pipefail`.
7. `pyproject.toml` en la raíz **solo para tooling** (ruff, mypy, pytest); las
   dependencias de ejecución van en el `requirements.txt` de cada servicio.

**Validación**

```bash
docker compose config >/dev/null && echo OK
ls services/{api-gateway,cotizador,gestion-errores,votacion} scripts docs
```

**Resultado esperado:** `OK` impreso, sin advertencias de Compose; los cuatro
directorios de servicio existen bajo `services/`; no hay ningún archivo de
entorno fuera de la raíz.

---

## F1 · Contratos y utilidades locales

**Objetivo:** que cada servicio pueda construirse y probarse desde su carpeta,
sin una librería compartida ni un contexto de Docker situado en la raíz.

**Pasos**

1. Cada paquete contiene su módulo local `common/contracts.py` con las
   dataclasses que necesita — `Asegurado`, `SolicitudCotizacion`,
   `ResultadoCotizacion`, `SobreSolicitud`, `SobreRespuesta`. Serialización
   explícita a/desde `dict` con `Decimal` como `str`.
2. `tarifario.py`: tablas `2026.02` y `2025.11` como constantes `Decimal`, con la
   función `tasa_base_mil(edad, version)`.
3. `pricing.py`: `calcular(solicitud, fecha_calculo, version) -> ResultadoCotizacion`
   implementando §2.3, y `validar(resultado, solicitud) -> list[Violacion]`
   implementando §2.4.
4. `hashing.py`: `json_canonico()` y `resultado_hash()` según §2.5.
5. `ids.py`: `nuevo_correlation_id()` sobre `uuid.uuid7()`.
6. `logging_.py`: logging estructurado JSON con `correlation_id` obligatorio.
7. `errors.py`: excepciones de dominio + traductor a RFC 9457.
8. Los tests de dominio pertenecen al cotizador, dueño del cálculo y tarifario.
9. Tests: ejemplo canónico de §2.3, tabla de rangos de edad, `parametrize` de
   los 4 casos de validación, y **test de determinismo**: 1000 ejecuciones de la
   misma entrada producen el mismo hash.

**Validación**

```bash
PYTHONPATH=services/cotizador/src pytest services/cotizador/tests -q
python -c "
from cotizador.common.pricing import calcular
# ...ejemplo canónico...
print(r.prima_mensual, r.prima_anual)"
```

**Resultado esperado:** todos los tests en verde y la impresión exacta
`90348.41 1084180.92`. Si sale otro número, el tarifario o el orden de redondeo
están mal y **no se puede avanzar**: todas las fases siguientes dependen de este
valor.

---

## F2 · `queue-service` (Redis)

**Objetivo:** cola arriba, sana, y fan-out demostrado antes de que exista un solo
consumidor real.

**Pasos**

1. `queue-service/redis.conf`: `appendonly yes`, `maxmemory-policy noeviction`
   (perder un evento de cotización no es aceptable), `save` desactivado en dev.
2. `queue-service/docker-compose.yaml`: `redis:8.10-alpine`, red `data` únicamente
   (sin puertos publicados), volumen nombrado `solventa_redisdata`,
   `healthcheck: redis-cli ping`, `restart: unless-stopped`.

**Validación**

```bash
docker compose up -d redis
docker compose ps                       # healthy
docker compose exec redis redis-cli XADD cot:req '*' tipo prueba
docker compose exec redis redis-cli XGROUP CREATE cot:req grupo-a 0
docker compose exec redis redis-cli XGROUP CREATE cot:req grupo-b 0
docker compose exec redis redis-cli XGROUP CREATE cot:req grupo-c 0
for g in a b c; do
  docker compose exec redis redis-cli XREADGROUP GROUP grupo-$g c1 COUNT 1 STREAMS cot:req '>'
done
```

**Resultado esperado:** el servicio aparece `healthy`; **los tres grupos leen el
mismo mensaje**. Esto es la prueba de que la topología es fan-out y no competing
consumers. Si un grupo lee y los otros no reciben nada, la configuración está
mal y todo el experimento sería inválido.

---

## F3 · `cotizador` (worker puro)

**Objetivo:** una réplica que consume del stream, calcula y responde. Tonta a
propósito: no sabe que existe la votación.

**Por qué no lleva Flask.** El cotizador no recibe peticiones HTTP de nadie: su
trabajo es `XREADGROUP` → calcular → `LPUSH`. Meterle un servidor web pondría
dos responsabilidades en un contenedor y obligaría a fijar gunicorn a un solo
worker para que la salud fuese inequívoca. Como worker puro, además, el
healthcheck resulta **más fuerte** que un endpoint HTTP: el proceso refresca una
clave de latido en Redis en cada vuelta del bucle y el chequeo mira esa clave,
de modo que un bucle consumidor colgado se detecta. Un `/health` de Flask
seguiría respondiendo con el consumidor muerto.

**Pasos**

1. `src/cotizador/config.py`: configuración leída del entorno a una dataclass
   inmutable — `COTIZADOR_ID`, `REDIS_URL`, `FAULT_MODE`, `TARIFARIO_VERSION`,
   nombres de stream y prefijo de respuestas, TTL del latido.
2. `src/cotizador/faults.py`: los nueve modos de §2.6, envolviendo el cálculo del
   dominio. Ningún modo duplica la fórmula: los que alteran la tabla construyen
   un `Tarifario` corrompido y llaman al mismo `pricing`.
3. `src/cotizador/consumer.py`: creación idempotente del consumer group
   `grupo-{id}`, bucle `XREADGROUP` con `block` corto para poder atender
   `SIGTERM`, `LPUSH cot:resp:{correlation_id}` + `EXPIRE 60` (evita fugas si
   Votación ya se rindió) y `XACK` tras responder.
4. `src/cotizador/health.py`: refresco del latido `cot:hb:{id}` con TTL, y el
   comando que usa el healthcheck del contenedor.
5. `src/cotizador/__main__.py`: arranque, logging estructurado y apagado limpio
   ante `SIGTERM`.
6. `Dockerfile` multi-stage sobre `python:3.14.6-slim`, `context` = carpeta del
   servicio, usuario `10001` y `CMD` en forma exec.
7. `services/cotizador/docker-compose.yaml`: anchor `x-cotizador` +
   `cotizador-a`, `cotizador-b`, `cotizador-c` sobre **una sola imagen**, cada
   uno con su `COTIZADOR_ID` y su `FAULT_MODE`.
8. Tests: unitarios de `faults.py` (cada modo altera el resultado como dice
   §2.6, y los que deben ser invisibles a las reglas de validez lo son) e
   integración del consumidor contra el Redis del stack.

**Validación**

```bash
docker compose up -d --build cotizador-a cotizador-b cotizador-c
docker compose exec cotizador-a id                 # uid=10001, no root
docker compose ps                                  # los 3 healthy
./scripts/api-calls/publicar-solicitud.sh          # publica el ejemplo canónico
docker compose exec redis redis-cli LRANGE cot:resp:<correlation_id> 0 -1
```

**Resultado esperado:** `uid=10001`; las tres réplicas `healthy`; la lista de
respuestas contiene **exactamente 3 elementos**, con `cotizador_id` `A`, `B` y
`C`, `prima_mensual = "90348.41"` en los tres y **el mismo `resultado_hash`**.
Un hash distinto entre réplicas sanas significa que el cálculo no es
determinista: hay que arreglarlo aquí, no en Votación.

Segunda validación, con fallo inyectado:

```bash
FAULT_B=premium_offset docker compose up -d cotizador-b
# volver a publicar y releer la lista
```

**Resultado esperado:** A y C mantienen `90348.41` y su hash; B devuelve
`103900.67` con un hash distinto.

## F4 · `gestion-errores`

**Objetivo:** registrar la evidencia. Es el servicio más simple y debe existir
antes que Votación, que es quien lo llama.

**Pasos**

1. `POST /v1/incidentes` con el envelope de incidente: `correlation_id`,
   `tipo` (`divergencia_resultado` \| `regla_de_validez` \| `sin_quorum` \|
   `replica_no_responde`), `replicas_divergentes`, `valor_consenso`,
   `valores_recibidos`, `detectado_en`.
2. Persistencia: `append` a JSONL en un volumen nombrado. Suficiente y auditable
   para el experimento; una base de datos aquí sería andamiaje.
3. `GET /v1/incidentes?correlation_id=...` para las aserciones del experimento.
4. `GET /v1/metricas`: contadores de incidentes por tipo — de aquí sale el
   numerador del ≥99 % de ASR-11.
5. Endpoint **no bloqueante para el que reporta**: responde `202 Accepted` y
   escribe en background. Votación nunca debe esperar a este servicio: eso
   consumiría presupuesto de latencia de ASR-12.
6. `Dockerfile` + `docker-compose.yaml` (red `backend` únicamente).

**Validación**

```bash
curl -s -XPOST localhost:8003/v1/incidentes -d @docs/ejemplos/incidente.json \
     -H 'content-type: application/json' -o /dev/null -w '%{http_code} %{time_total}\n'
curl -s localhost:8003/v1/metricas | jq
```

**Resultado esperado:** `202` en **menos de 20 ms**; `/v1/metricas` muestra
`divergencia_resultado: 1`; el JSONL del volumen contiene una línea con el
`correlation_id` enviado.

---

## F5 · `votacion` (el corazón del experimento)

**Objetivo:** detectar (ASR-11) y enmascarar (ASR-12) dentro del presupuesto de
latencia.

**Pasos**

1. `POST /v1/cotizaciones` interno: valida, **normaliza** (fija `fecha_calculo`
   y `tarifario_version`, §1.4) y genera el envelope.
2. `XADD cot:req` una sola vez — el fan-out lo hacen los consumer groups.
3. Recolección: `BLPOP cot:resp:{correlation_id}` en bucle con **presupuesto
   global de 250 ms**, no un timeout por respuesta.
4. **Corte anticipado por quórum, con ventana de gracia.** En cuanto hay 2
   huellas válidas iguales el veredicto ya está decidido, pero no se corta en
   seco: se abre una ventana de **25 ms** para recoger a las rezagadas. Esa
   espera NO cambia lo que se responde; existe solo para poder *ver* a la
   réplica divergente y registrarla.

   Sin la gracia, ASR-12 se cumpliría y **ASR-11 fallaría de forma
   intermitente**: si las dos primeras respuestas leídas coinciden, se cortaría
   antes de leer la tercera —la errónea— y la detección dependería del orden de
   llegada. Con tres réplicas, eso ocurriría en dos de cada tres casos.

   El corte sigue acotando el peor caso: una réplica `slow` (400 ms) o `crash`
   nunca cuesta el presupuesto entero. Y el corte por quórum **solo se abre con
   respuestas que ya pasaron las reglas de validez**: dos réplicas rotas del
   mismo modo producen la misma huella, y contarlas como acuerdo cortaría la
   recolección antes de leer a la réplica sana.

   Nota de infraestructura: Redis revisa los clientes bloqueados a `hz` veces
   por segundo. Con el valor por defecto (10) un timeout de `BLPOP` de 25 ms
   tarda ~105 ms en vencer. `queue-service/redis.conf` fija `hz 100` para bajar
   esa resolución a ~10 ms.
5. Resolución del veredicto, en este orden:
   - descartar los resultados que violen una regla de validez (§2.4);
   - agrupar los supervivientes por `resultado_hash`;
   - si un grupo tiene ≥ `QUORUM` (=2) → `COTIZADO`, ese es el valor;
   - si hay respuestas pero ninguna alcanza quórum → `COTIZADO_DEGRADADO` si
     exactamente una supera todas las reglas de validez; si no, `RECHAZADO` (503);
   - si vence el presupuesto sin respuestas → `RECHAZADO` (504).
6. Reporte a `gestion-errores` **después** de haber respondido al cliente, en un
   hilo aparte (`fire-and-forget` con reintento acotado).
7. `limpieza`: `DEL cot:resp:{correlation_id}` tras resolver.
8. Métricas: `latencia_consenso_ms`, `respuestas_recibidas`, `divergencias`.
9. Tests con dobles de Redis: 3 iguales · 2 iguales + 1 divergente · 3 distintos ·
   1 sola respuesta · 0 respuestas · 1 fuera de rango + 2 iguales.

**Validación**

```bash
# caso sano
curl -s -XPOST localhost:8002/v1/cotizaciones -d @docs/ejemplos/solicitud.json \
     -H 'content-type: application/json' | jq '.estado, .cotizacion.prima_mensual, .consenso'

# caso con fallo en B
FAULT_B=premium_offset docker compose up -d cotizador-b
curl -s -XPOST localhost:8002/v1/cotizaciones -d @docs/ejemplos/solicitud.json \
     -H 'content-type: application/json' | jq '.estado, .cotizacion.prima_mensual, .consenso'
curl -s localhost:8003/v1/metricas | jq
```

**Resultado esperado:**

| Escenario | `estado` | `prima_mensual` | `consenso.divergencia_detectada` | Incidente registrado |
|---|---|---|---|---|
| Sin fallo | `COTIZADO` | `90348.41` | `false` | no |
| `FAULT_B=premium_offset` | `COTIZADO` | **`90348.41`** | `true`, `replicas_divergentes: ["B"]` | sí |
| `FAULT_B=crash` | `COTIZADO` | `90348.41` | `true`, `respuestas_recibidas: 2` | sí |
| `FAULT_B` y `FAULT_C` distintos | `COTIZADO_DEGRADADO` | valor de A | `true` | sí |

La celda en negrita es ASR-12: **el cliente recibe el valor correcto pese al
fallo activo**. Y `latencia_consenso_ms` debe salir por debajo de 250 ms en
todos los casos, incluido `crash`.

---

## F6 · `api-gateway`

**Objetivo:** la puerta. Sin lógica de negocio.

**Pasos**

1. `POST /v1/cotizaciones` público: exige `request_id` en el JSON, genera el
   `correlation_id` (`uuid7`) y reenvía a la URL de cotización configurada.
2. Añade `X-Correlation-Id` a toda respuesta, incluidas las de error.
3. Propaga el cuerpo y el estado HTTP que devuelve el servicio interno.
4. Devuelve `504` si vence el timeout y `503` si no puede conectarse.
5. Registra `request_id`, `correlation_id`, estado y tiempo total en JSON.
6. Es el único servicio conectado a la red `edge`.

**Validación**

```bash
curl -si -XPOST localhost:8000/v1/cotizaciones \
     -H 'content-type: application/json' -d @docs/ejemplos/solicitud.json | head -20
curl -si -XPOST localhost:8000/v1/cotizaciones \
     -H 'content-type: application/json' -d '{"producto":"vida_hipotecario"}' | jq
docker compose exec cotizador-a curl -s localhost:8000/health   # debe fallar
```

**Resultado esperado:** `200` con `X-Correlation-Id`; `400` si falta
`request_id`; propagación de los estados devueltos por el servicio interno; y
la última llamada **debe fallar por red**,
probando que los cotizadores no alcanzan el gateway (aislamiento de zonas).

---

## F7 · Experimento y medición

**Objetivo:** producir los números que exigen ASR-11 y ASR-12.

**Pasos**

1. `scripts/experiment/inyectar.sh <replica> <modo>`: reinicia una réplica con su
   `FAULT_MODE` y espera a que quede `healthy`.
2. `scripts/experiment/carga.js` (k6): 500 cotizaciones/min sostenidas, entradas
   variadas (edad, suma, plazo, canal) para no medir siempre el mismo camino.
3. **Corrida A — línea base:** sin fallo, 10 minutos. Registra el p95 limpio.
4. **Corrida B — detección:** inyecta cada uno de los 8 modos de fallo, 1000
   cotizaciones por modo, y contrasta los incidentes de `/v1/metricas` contra el
   número de solicitudes inyectadas.
5. **Corrida C — enmascaramiento:** con `premium_offset` activo en B durante toda
   la corrida, comparar el p95 contra la línea base y verificar que **ninguna**
   respuesta lleve la prima errónea.
6. `scripts/experiment/reporte.py`: genera la tabla de resultados en Markdown.

**Validación y criterio de aceptación**

| ASR | Métrica | Umbral | Cómo se obtiene |
|---|---|---|---|
| **ASR-11** | Tasa de detección | **≥ 99 %** | incidentes registrados ÷ fallos inyectados, por modo |
| **ASR-12** | Retardo añadido | **≤ 300 ms** sobre el p95 base | `p95(corrida C) − p95(corrida A)` |
| **ASR-12** | Primas erróneas entregadas | **0** | ninguna respuesta distinta del valor de consenso sano |

**Resultado esperado:** los tres umbrales cumplidos, y un informe que además
documente el límite conocido del diseño: con tres réplicas idénticas, un error
sistemático en el tarifario produce tres resultados iguales y erróneos, y la
votación reportaría consenso. El experimento demuestra detección de fallos **no
correlacionados**, no corrección de la lógica actuarial.

---

# 4. Riesgos abiertos

1. **Redis es punto único de falla** en esta topología: si cae, cae el journey
   completo. Aceptable para el experimento, pero debe quedar escrito.
2. **La cola en un journey síncrono** añade saltos que un fan-out HTTP directo no
   tendría. Es lo que impone el diagrama de despliegue; es el punto de mayor
   presión sobre el presupuesto de 300 ms.
3. **Réplicas idénticas** no detectan fallos correlacionados (ver F7).
4. **`redis:8.10-alpine` es un tag flotante.** Sirve en desarrollo; para una
   corrida de experimento reproducible conviene fijar `8.10.1-alpine3.23` o el
   digest, para que el resultado no cambie si Docker Hub mueve el tag.
