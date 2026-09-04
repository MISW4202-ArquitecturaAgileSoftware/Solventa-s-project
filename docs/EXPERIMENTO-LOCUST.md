# Experimento de detección y enmascaramiento — ejecución e integración Locust

Documento nuevo: cómo correr el experimento, cómo está integrada Locust, qué
significan sus gráficos, qué muestra el HTML de resultados y cómo funciona el
experimento de punta a punta.

Los ASR formales están en [ASRs-experimento.md](ASRs-experimento.md). El
informe numérico de una corrida lo genera `reporte.py` en
[RESULTADOS-EXPERIMENTO.md](RESULTADOS-EXPERIMENTO.md); ningún número de ese
archivo se escribe a mano.

---

## 1. Qué se mide

| ASR | Hipótesis | Umbral |
|---|---|---|
| **ASR-11** detección | El sistema identifica un cálculo erróneo **antes** de entregarlo al canal, en horario pico | **≥ 99 %** de los fallos **efectivos**, en **todos** los modos |
| **ASR-12** enmascaramiento | Con un cotizador fallando, el cliente recibe la prima correcta y el journey no se encarece | `p95(C) − p95(A) ≤ 300 ms` y **0 primas erróneas** |

La táctica bajo prueba es votación 2 de 3. Locust no es la táctica: es el
cliente de carga y el oráculo que verifica la prima.

---

## 2. Cómo ejecutar

### Requisitos

- Docker Compose y las imágenes `solventa/*:dev`.
- `.env` copiado desde `example.env`.
- `.venv` con Locust (`scripts/bootstrap.sh`).
- Stack arriba:

```bash
docker compose up -d --wait --pull never
```

Si el build no resuelve PyPI desde Docker:

```bash
docker build --network=host -t solventa/api-gateway:dev \
  -f services/api-gateway/Dockerfile services/api-gateway
# repetir para votacion, gestion-errores y cotizador
```

### Comandos

Desde la raíz del repositorio:

```bash
./scripts/experiment/correr.sh --rapido      # corto (200 / 100×8 / 200)
./scripts/experiment/correr.sh               # oficial (~40 min: 5000 / 8×1000 / 5000)
./scripts/experiment/correr.sh --sin-pausa   # no espera Enter entre modos
./scripts/experiment/correr.sh --sin-ui      # sin tableros (CI / SSH)
```

`correr.sh` activa el venv y llama a `scripts/experiment/correr.py`.
Siguen valiendo `RAPIDO=1` y `SIN_UI=1`.

### Pantallas

| URL | Qué es | ¿Se cae entre modos? |
|---|---|---|
| http://127.0.0.1:8090 | Tablero de resultados ASR (§6) | No |
| http://127.0.0.1:8089 | UI de Locust, carga HTTP (§5) | Sí: un proceso por bloque |

Con UI, al terminar un bloque Locust **deja los gráficos**. En la terminal:
*Enter para el siguiente modo*. Recién entonces se mata ese Locust, se
inyecta el siguiente fallo en B y arranca otro. Si `:8089` no reconecta,
recargar. `:8090` no hace falta recargarlo.

Al final, Enter cierra el proceso. El Markdown queda en
`docs/RESULTADOS-EXPERIMENTO.md`.

### Puertos (`.env`)

| Variable | Default | Uso |
|---|---|---|
| `PUERTO_GATEWAY` | 8000 | Entrada de Locust |
| `PUERTO_VOTACION` | 8002 | Depuración; el ASR no entra por aquí |
| `PUERTO_GESTION_ERRORES` | 8003 | Numerador ASR-11 (`/v1/metricas`) |
| `PUERTO_LOCUST` | 8089 | UI Locust |
| `PUERTO_TABLERO` | 8090 | Tablero de resultados |

---

## 3. Cómo funciona el experimento

### Journey de cada cotización

Las tres corridas usan **el mismo camino**. Locust nunca habla con un
cotizador ni con Votación a pelo.

```text
Locust (10 usuarios, ~500 cotizaciones/min)
  │  POST /v1/cotizaciones
  ▼
API Gateway                         correlation_id
  │
  ▼
Votación                            publica UNA vez en Redis (fan-out)
  │                                 presupuesto 250 ms + 25 ms de gracia
  ├──────────────► Gestión de Errores   (incidente, hilo aparte)
  ▼
Cotizadores A, B y C                misma imagen; B puede tener FAULT_MODE
  │
  └──────────────► Votación         mayoría 2 de 3 → respuesta al cliente
```

A, B y C **siempre** están arriba y **siempre** reciben la solicitud.
Votación **siempre** exige dos resultados idénticos. No calcula primas y no
conoce los modos de fallo: compara el resultado funcional completo.

### Por qué tres corridas

No son tres arquitecturas. Son tres protocolos de medición.

| Corrida | Estado de B | Pregunta | Por qué no se fusiona |
|---|---|---|---|
| **A** | `none` (las tres sanas) | ¿p95 **sin** fallo? | Si B ya fallara, el p95 incluiría el enmascaramiento |
| **B** | un modo a la vez, 8 bloques | ¿detección ≥ 99 % de **ese** fallo? | Mezclar modos mezcla incidentes |
| **C** | `premium_offset` sostenido | ¿prima correcta y retardo ≤ 300 ms? | Hay que restar `p95(C) − p95(A)` |

### Cómo se fuerza el error en B

Locust envía solicitudes **válidas**. El fallo está en el contenedor B.

```text
inyectar.sh b premium_offset
  → export FAULT_B=premium_offset
  → docker compose up -d --wait cotizador-b
  → comprueba printenv FAULT_MODE
```

El worker lee `FAULT_MODE` al arrancar y lo aplica en cada cálculo
(`faults.calcular`). A y C no se reinician. El modo no cambia a mitad de un
bloque de Locust: primero termina Locust (y Enter, si hay UI), después se
recrea B.

### Modos y clasificación de Votación

Votación no etiqueta “premium_offset”. Etiqueta lo que observa:

| Tipo de incidente | Cuándo |
|---|---|
| `divergencia_resultado` | Un resultado no coincide con la mayoría |
| `replica_no_responde` | Falta una réplica o llegó sin resultado |
| `sin_quorum` | Hay respuestas pero ninguna llega a 2 iguales (esta corrida no lo usa) |

| Modo en B | Qué hace B | Qué ve Votación |
|---|---|---|
| `premium_offset` | Prima × 1.15 | divergencia |
| `rounding_drift` | Trunca a pesos | divergencia |
| `out_of_range` | Prima × 500 | divergencia (Votación no valida rangos) |
| `silent_zero` | Devuelve `0.00` | divergencia |
| `rate_table_stale` | Tarifario `2025.11` | divergencia |
| `factor_skip` | Factores de clase = `1.00` | divergencia **salvo clase 1** |
| `slow` | Espera 400 ms | no entra en 250 ms → no responde |
| `crash` | No publica | no responde |

`factor_skip` en clase ocupacional 1 no altera la prima (el factor ya es
`1.00`). El denominador de ASR-11 es `fallos_efectivos`, no las requests
enviadas.

### Cierre de las hipótesis

- **ASR-11:** `incidentes / fallos_efectivos ≥ 0.99` en **cada** modo. El
  reporte a Gestión de Errores es asíncrono: se espera 500 ms de silencio en
  `/v1/metricas` antes de leer el numerador.
- **ASR-12:** Locust recalcula la prima con `experiment_common` y
  `emitido_en`. `p95(C) − p95(A) ≤ 300 ms` y `primas_erroneas == 0`.

### Límite del diseño

Tres réplicas **idénticas**. Un error sistemático en la fórmula produce tres
resultados iguales y malos: consenso sobre el valor erróneo, 0 incidentes. El
experimento cubre fallos **no correlacionados**.

---

## 4. Integración con Locust

Locust corre en el host (`subprocess`), no en las imágenes.

### Ritmo y usuario

10 usuarios × `constant_pacing(1.2 s)` ≈ **8.33 req/s ≈ 500/min**. El primer
POST se desfasa 0.12 s entre usuarios para no salir en ráfaga.

`CotizadorUser` solo hace `POST /v1/cotizaciones` (nombre `cotizar`). Cualquier
HTTP cuenta como estímulo. Una prima distinta del oráculo es *failure* de
Locust (ASR-12), no el incidente de Votación.

Al llegar a `LOCUST_N`:

- con UI: `runner.stop()` — el test acaba, la página **sigue**;
- headless: `runner.quit()` — el proceso termina.

### Archivos (`scripts/experiment/`)

```text
correr.py / correr.sh     orquesta A → 8×B → C → informe
locustfile.py             CotizadorUser
locust_carga/
  solicitudes.py          payloads deterministas
  oraculo.py              prima esperada (ASR-12)
  prediccion.py           ¿el modo altera esta request? (denominador ASR-11)
  percentil.py            p50/p95/p99 crudos
  metricas_run.py         JSON por bloque
  drenaje.py              espera silencio en /v1/metricas
inyectar.sh               FAULT_B + recrea B
anotar_deteccion.py       tasa = incidentes / fallos_efectivos
tablero.py + tablero.html :8090
reporte.py                Markdown
experiment_common/        tarifario y fórmula del oráculo
```

Los servicios no importan Locust. Locust no importa `cotizador.faults`. El
puente es HTTP al gateway y `FAULT_B` en Docker.

Cada bloque escribe un JSON en `scripts/experiment/resultados/` (gitignored).

---

## 5. Gráficos de Locust (`:8089`)

Tres gráficos de fábrica. Miden el HTTP del cliente.

**Total Requests per Second.** Cotizaciones por segundo. Debe rondar 8.3.
*Failures* de Locust = timeout o prima ≠ oráculo, no incidentes JSONL.

**Response Times (ms).** Latencia del journey (gateway → votación → réplicas →
respuesta). Por defecto dos líneas:

| Percentil | Significado |
|---|---|
| **50 % (p50)** | La mitad de las cotizaciones tardó menos. Caso típico. |
| **95 % (p95)** | El 95 % tardó menos. Es el de ASR-12. |

No es un promedio. p50 = 62 ms y p95 = 89 ms: lo normal ~60 ms y casi nadie
pasó de ~90 ms. ASR-12 usa `p95(C) − p95(A)` calculado sobre **muestras
crudas** del JSON, no sobre el histograma redondeado de Locust.

**Number of Users.** Tras el spawn debe quedarse en 10.

Esos tres gráficos no se reconfiguran sin parchear Locust y se reinician en
cada bloque. El tablero `:8090` acumula lo que Locust no guarda.

---

## 6. Tablero HTML (`:8090`)

Página propia. Acumula A, cada modo B y C.

### Cabecera

| Campo | Significado |
|---|---|
| Fase (amarillo) | Paso actual: preparación, A, `B · factor_skip`, C, informe |
| Actualizado | Última escritura de `estado.json` |

Chips: pendiente, en curso, hecho, parcial.

### ASR-11

| Columna | Significado |
|---|---|
| Modo | `FAULT_MODE` en B |
| Vía | Cómo *debería* detectarlo Votación |
| Efectivos | Requests en las que el modo sí altera el resultado |
| Incidentes | Persistidos en Gestión de Errores |
| Tasa | `incidentes / efectivos`. Verde si ≥ 99 % |

El veredicto usa el **peor** modo, no el promedio. Si uno baja de 99 %, ASR-11
no cumple.

### ASR-12

| Recuadro | Significado |
|---|---|
| A · p95 base | p95 con las tres réplicas sanas |
| C · p95 con fallo | p95 con `premium_offset` en B |
| Retardo añadido | `p95(C) − p95(A)`. Umbral ≤ 300 ms |
| Primas erróneas (C) | 200 cuya prima ≠ oráculo. Umbral: 0 |

CUMPLE solo si se cumplen **los dos** umbrales.

---

## 7. Informe Markdown

`docs/RESULTADOS-EXPERIMENTO.md`, al final de la corrida. Mismos umbrales, más
detalle de latencia (p50, p95, p99, máx, tasa real/min). La columna
“Cotizaciones” de ASR-11 es `fallos_efectivos`. La nota de `factor_skip`
explica por qué efectivos &lt; requests enviadas.

---

## 8. Criterio de aceptación

| ASR | Métrica | Cómo se obtiene |
|---|---|---|
| 11 | ≥ 99 % en **cada** modo | incidentes ÷ `fallos_efectivos` |
| 12 | retardo p95 ≤ 300 ms | `p95(C) − p95(A)` |
| 12 | 0 primas erróneas | oráculo Locust, una a una |

El numerador oficial de detección es Gestión de Errores, no el bloque
`consenso` de la respuesta HTTP.
