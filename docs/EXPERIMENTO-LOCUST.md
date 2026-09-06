# Experimento de detección y enmascaramiento — ejecución e integración Locust

Cómo correr el experimento, cómo está integrada Locust, qué significan sus
gráficos, qué muestra el tablero HTML y cómo funciona el experimento de punta
a punta.

Los ASR formales están en [ASRs-experimento.md](ASRs-experimento.md). El
informe numérico de una corrida lo genera `reporte.py` en
[RESULTADOS-EXPERIMENTO.md](RESULTADOS-EXPERIMENTO.md); ningún número de ese
archivo se escribe a mano.

---

## 1. Qué se mide

| ASR | Hipótesis | Umbral |
|---|---|---|
| **ASR-11** detección | El sistema identifica un cálculo erróneo **antes** de entregarlo al canal, en horario pico | **≥ 99 %** de los fallos **efectivos**, en **todos** los modos |
| **ASR-12** enmascaramiento | Con un cotizador fallando, el cliente recibe la prima correcta y el journey no se encarece | retardo total añadido `media(C) − media(A) ≤ 300 ms` y **0 primas erróneas** |

La táctica bajo prueba es votación 2 de 3 sobre el `ResultadoCotizacion`
completo. Locust no es la táctica: es el cliente de carga y el oráculo que
verifica la prima entregada.

---

## 2. Cómo ejecutar

### Requisitos

En el sistema: Git, Docker Engine + Compose v2, Python 3.14, curl. El usuario
tiene que poder ejecutar `docker` sin error (`docker info`).

Un solo script deja `.env`, venv, imágenes y stack listos, y hace un POST de
humo al gateway:

```bash
./scripts/preparar.sh
```

Si las imágenes ya existen: `./scripts/preparar.sh --sin-build`.

Pasos sueltos (equivalente):

```bash
cp -n example.env .env
./scripts/bootstrap.sh
source .venv/bin/activate
./scripts/build.sh          # si Docker no resuelve PyPI: docker compose build --network=host
./scripts/up.sh
```

Humo por el **gateway** (por ahí entra Locust, no por votación a pelo):

```bash
curl -s -XPOST "http://localhost:8000/v1/cotizaciones" \
  -H 'content-type: application/json' \
  -d @docs/ejemplos/solicitud.json | python -m json.tool | head -20
```

Debe salir `"estado": "COTIZADO"`.

Si quedó un Locust de una corrida anterior:

```bash
pkill -f 'locust -f' || true
```

### Comandos

Desde la raíz del repositorio. **`--sin-pausa` encadena A → 8×B → C sin pulsar
Enter.** Sin ese flag, al cerrar cada bloque la terminal pide Enter.

```bash
# Validar el stack (10–15 min): 200 / 8×100 / 200
./scripts/experiment/correr.sh --rapido --sin-pausa

# Oficial (~40 min): 5000 / 8×1000 / 5000
./scripts/experiment/correr.sh --sin-pausa

# Mismos tamaños, parando a mirar los gráficos de cada bloque (Enter en la terminal)
./scripts/experiment/correr.sh --rapido
./scripts/experiment/correr.sh

# Sin tableros (CI / SSH)
./scripts/experiment/correr.sh --rapido --sin-ui
```

`correr.sh` activa el venv y llama a `scripts/experiment/correr.py`.
Siguen valiendo `RAPIDO=1`, `SIN_UI=1` y `SIN_PAUSA=1`.

`--rapido` no sustituye al informe oficial: el n es más chico.

### Pantallas

| URL | Qué es | ¿Se cae entre modos? |
|---|---|---|
| http://127.0.0.1:8090 | Tablero ASR, catálogo y gráficos del experimento (§6) | No |
| http://127.0.0.1:8089 | UI de Locust, carga HTTP (§5) | Sí: un proceso por bloque |

Con `--sin-pausa`, al llegar a N se escribe el JSON, se mata ese Locust y
arranca el siguiente modo. Si `:8089` queda en blanco, recargar. `:8090` no
hace falta recargarlo durante la corrida (sí si cambiaste `tablero.html`).

Sin `--sin-pausa`, al llegar a N los usuarios **siguen en 10** y dejan de
hacer POST (RPS → 0). No es un crash: en la terminal aparece *Enter para el
siguiente modo*. Recién entonces se mata Locust, se inyecta el siguiente
fallo en B y arranca otro proceso.

Al final, con UI, Enter cierra el orquestador. El Markdown queda en
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
| **A** | `none` (las tres sanas) | ¿latencia media **sin** fallo? | Si B ya fallara, la media incluiría el enmascaramiento |
| **B** | un modo a la vez, 8 bloques | ¿detección ≥ 99 % de **ese** fallo? | Mezclar modos mezcla incidentes |
| **C** | `premium_offset` sostenido | ¿prima correcta y retardo ≤ 300 ms? | Hay que restar `media(C) − media(A)` |

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
bloque de Locust: primero termina el bloque (y Enter, si no hay `--sin-pausa`),
después se recrea B.

### Modos y clasificación de Votación

Votación no etiqueta “premium_offset”. Etiqueta lo que observa:

| Tipo de incidente | Cuándo |
|---|---|
| `divergencia_resultado` | Un resultado no coincide con la mayoría |
| `replica_no_responde` | Falta una réplica o llegó sin resultado |
| `sin_quorum` | Hay respuestas pero ninguna llega a 2 iguales (raro: una réplica sana se atrasó mientras B ya fallaba) |

| Modo en B | Qué hace B | Qué ve Votación | Trampa |
|---|---|---|---|
| `premium_offset` | Prima × 1.15 | divergencia | Ninguna: altera todas |
| `rounding_drift` | Trunca a pesos | divergencia | Desvío de céntimos |
| `out_of_range` | Prima × 500 | divergencia | No hay regla de validez en Votación |
| `silent_zero` | Devuelve `0.00` | divergencia | El cliente no ve el cero |
| `rate_table_stale` | Tarifario `2025.11` | divergencia | Solo si las dos tablas dan primas distintas |
| `factor_skip` | Factores de clase = `1.00` | divergencia **salvo clase 1** | Clase 1 ya vale 1.00 |
| `slow` | Espera 400 ms | no entra en 250 ms → no responde | Presupuesto de consenso |
| `crash` | No publica | no responde | Sin XACK |

El denominador de ASR-11 es `fallos_efectivos` (el modo sí altera esa request
y llegó a Votación), no las requests enviadas. Lo predice Locust con el
tarifario del oráculo, no importando `cotizador.faults`.

El mismo catálogo se muestra en el tablero `:8090`.

### Cierre de las hipótesis

- **ASR-11:** `incidentes / fallos_efectivos ≥ 0.99` en **cada** modo. El
  reporte a Gestión de Errores es asíncrono: se espera 500 ms de silencio en
  `/v1/metricas` antes de leer el numerador (`tasa_deteccion` en el JSON).
- **ASR-12:** Locust recalcula la prima con `experiment_common` y
  `emitido_en`. `media(C) − media(A) ≤ 300 ms` y `primas_erroneas == 0`.

No se cruza por `correlation_id`. El numerador es el contador de incidentes
en Gestión de Errores; el denominador lo anota Locust.

### Límite del diseño

Tres réplicas **idénticas**. Un error sistemático en la fórmula produce tres
resultados iguales y malos: consenso sobre el valor erróneo, 0 incidentes.
El oráculo del cliente lo marcaría como prima errónea en C, no como
incidente de ASR-11. El experimento cubre fallos **no correlacionados**.

---

## 4. Integración con Locust

Locust corre en el host (`subprocess`), no en las imágenes.

### Ritmo y usuario

10 usuarios × `constant_pacing(1.2 s)` ≈ **8.33 req/s ≈ 500/min**. El primer
POST se desfasa 0.12 s entre usuarios para no salir en ráfaga.

`CotizadorUser` solo hace `POST /v1/cotizaciones` (nombre `cotizar`). Cualquier
HTTP cuenta como estímulo. Una prima distinta del oráculo es *failure* de
Locust (ASR-12), no el incidente de Votación.

Al llegar a `LOCUST_N`, un greenlet aparte escribe el JSON del bloque:

- **con UI:** no se llama `runner.stop()` (eso ponía Users = 0 y parecía un
  crash). Los usuarios siguen vivos y `cotizar` retorna sin POST. `correr.py`
  desbloquea al ver el JSON.
- **headless:** `runner.quit()` y el proceso termina.

`correr.py` redirige stdout/stderr de Locust a
`scripts/experiment/resultados/<bloque>.locust.log`.

### Archivos (`scripts/experiment/`)

```text
correr.py / correr.sh     orquesta A → 8×B → C → informe
locustfile.py             CotizadorUser
locust_carga/
  solicitudes.py          payloads deterministas
  oraculo.py              prima esperada (ASR-12)
  prediccion.py           ¿el modo altera esta request? (denominador ASR-11)
  percentil.py            p50/p99 crudos
  metricas_run.py         JSON por bloque
  drenaje.py              espera silencio en /v1/metricas
inyectar.sh               FAULT_B + recrea B
_metricas.py              GET /v1/metricas (numerador)
anotar_deteccion.py       tasa = incidentes / fallos_efectivos
tablero.py + tablero.html :8090 (catálogo + gráficos)
reporte.py                Markdown + catálogo de modos
experiment_common/        tarifario y fórmula del oráculo
```

Los servicios no importan Locust. Locust no importa `cotizador.faults`. El
puente es HTTP al gateway y `FAULT_B` en Docker.

Cada bloque escribe un JSON (y un `.locust.log`) en
`scripts/experiment/resultados/` (gitignored).

---

## 5. Gráficos de Locust (`:8089`)

Tres gráficos de fábrica. Miden el HTTP del cliente. Se reinician en cada
bloque porque hay un proceso Locust por corrida.

**Total Requests per Second.** Cotizaciones por segundo. Debe rondar 8.3
mientras el bloque está activo. Al llegar a N baja a 0: el cupo se llenó.
*Failures* de Locust = timeout o prima ≠ oráculo, no incidentes JSONL.

**Response Times (ms).** Latencia del journey (gateway → votación → réplicas →
respuesta). Por defecto Locust dibuja dos líneas de percentiles (la mediana y
el 95 %). Ninguna es el veredicto: ASR-12 usa la latencia **media**,
`media(C) − media(A)`, calculada sobre **muestras crudas** del JSON, no sobre
el histograma redondeado de Locust. La mediana (p50) y el p99 se guardan solo
como contexto.

**Number of Users.** Tras el spawn debe quedarse en 10. Con UI, al llegar a N
**sigue en 10** (ya no se llama `stop()`). Lo que cae es el RPS.

Esos tres gráficos no se reconfiguran sin parchear Locust. El tablero `:8090`
acumula lo que Locust no guarda entre modos.

---

## 6. Tablero HTML (`:8090`)

Página propia. Acumula A, cada modo B y C. El HTML no usa CDN: los gráficos
son SVG. Se refresca cada segundo leyendo `estado.json`.

### Cabecera

| Campo | Significado |
|---|---|
| Fase (amarillo) | Paso actual: preparación, A, `B · factor_skip`, C, informe |
| Actualizado | Última escritura de `estado.json` |

Chips: pendiente, en curso, hecho, parcial.

### ASR-11 (tabla)

| Columna | Significado |
|---|---|
| Modo | `FAULT_MODE` en B |
| Vía | Cómo *debería* detectarlo Votación |
| Efectivos | Requests en las que el modo sí altera el resultado |
| Incidentes | Persistidos en Gestión de Errores |
| Tasa | `incidentes / efectivos`. Verde si ≥ 99 % |

El veredicto usa el **peor** modo, no el promedio. Si uno baja de 99 %, ASR-11
no cumple.

### ASR-12 (KPI)

| Recuadro | Significado |
|---|---|
| A · media base | Latencia media con las tres réplicas sanas |
| C · media con fallo | Latencia media con `premium_offset` en B |
| Retardo añadido | `media(C) − media(A)`. Umbral ≤ 300 ms |
| Primas erróneas (C) | Respuestas de C cuya prima ≠ oráculo. Umbral: 0 |

CUMPLE solo si se cumplen **los dos** umbrales.

### Gráficos del tablero

No son los de Locust. Se van llenando al **cerrar** cada bloque.

| Gráfico | Qué muestra |
|---|---|
| Detección por modo | Barras de tasa vs la línea del 99 % |
| Latencia A vs C | media / p50 / p99 de la línea base y de C |
| Línea de tiempo | A → 8×B → C. Casillas iguales; arriba, duración en segundos |

Las etiquetas de la línea de tiempo van en corto (A, offset, skip, stale,
round, range, zero, slow, crash, C). El nombre completo sale al pasar el
cursor.

### Catálogo de modos

Ocho tarjetas: qué se inyecta en B, vía esperada, trampa (cuándo el modo no
altera) y tasa al cerrar el bloque. La tarjeta en curso se recuadra; al
cerrar, verde o rojo según CUMPLE. El texto vive en `reporte.py`
(`CATALOGO_MODOS`), no copiado a mano en el HTML.

---

## 7. Informe Markdown

`docs/RESULTADOS-EXPERIMENTO.md`, al final de la corrida. Mismos umbrales, más
detalle de latencia (media, p50, p99, máx, tasa real/min). La columna de ASR-11
es **Efectivos** (`fallos_efectivos`); la tasa sale de `tasa_deteccion` que
anotó `anotar_deteccion.py`. La nota de `factor_skip` explica por qué
efectivos &lt; requests enviadas.

---

## 8. Criterio de aceptación

| ASR | Métrica | Cómo se obtiene |
|---|---|---|
| 11 | ≥ 99 % en **cada** modo | incidentes ÷ `fallos_efectivos` |
| 12 | retardo total añadido ≤ 300 ms | `media(C) − media(A)` |
| 12 | 0 primas erróneas | oráculo Locust, una a una |

El numerador oficial de detección es Gestión de Errores (`GET /v1/metricas`),
no el bloque `consenso` de la respuesta HTTP ni los *failures* de Locust.
