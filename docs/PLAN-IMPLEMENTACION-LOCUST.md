# Plan de implementación — Locust para ASR-11 y ASR-12

Plan operativo para sustituir el generador de carga (`scripts/experiment/carga.py`)
por Locust, sin cambiar las tácticas bajo prueba ni el criterio de las hipótesis.

Locust no es el experimento. Es el instrumento que produce el estímulo de
**horario pico** que exigen los ASR. La inyección de fallos, el numerador de
detección y el veredicto siguen fuera de Locust.

---

## 0. Cómo se usa este plan

**Regla dura: una fase a la vez.** No se inicia una fase sin que la validación
de la anterior esté en verde. Cada fase declara *objetivo*, *pasos*, *comando
de validación* y *resultado esperado*.

Orden (dictado por lo que hay que medir, no por Locust):

```
L0 andamiaje  →  L1 usuario y ritmo  →  L2 oráculo ASR-12
              →  L3 denominador ASR-11 →  L4 orquestación  →  L5 corrida
```

Este plan **reemplaza el generador** descrito en `PLAN-IMPLEMENTACION.md` §F7
paso 2 (`carga.js` / `carga.py`). No reemplaza los pasos 1, 3, 4, 5 y 6:
`inyectar.sh`, las corridas A/B/C, `/v1/metricas` y `reporte.py` se conservan.

### Decisiones ya cerradas

| Decisión | Valor | Por qué |
|---|---|---|
| Dónde corre Locust | Host, contra `http://localhost:8000` | El cliente del ASR entra por el gateway. Locust no va en ninguna imagen de servicio. |
| Dependencia | `scripts/experiment/requirements.txt`, instalada en `.venv` | El experimentador no es un microservicio; no contamina `requirements.txt` de cotizador/votación/gateway. |
| Clase de usuario | `HttpUser` | 500 req/min no justifican `FastHttpUser`. |
| Ritmo | `constant_pacing(1.2)` × **10 usuarios** = **500/min** | `between()` mediría tiempo de pensar, no el pico. Es el equivalente del sleep al instante teórico de `carga.py`. |
| Spawn | `--users 10 --spawn-rate 10` | Los 10 usuarios nacen al inicio; la rampa no entra en la media. |
| Entrada | `POST /v1/cotizaciones` en el gateway | Pegarle a Votación (`:8002`) saltaría el journey que ASR-12 mide. |
| Solicitudes | Las mismas que `solicitud_de(indice)` en `carga.py` | Dos corridas con los mismos `n` son comparables. |
| Oráculo | `experiment_common.pricing.calcular` | Misma razón por la que se descartó k6: hay que verificar la prima una a una. |
| Latencia del veredicto | Muestras crudas en `test_stop`, no el histograma de Locust | Locust redondea sub-100 ms al ms. El umbral es 300 ms, pero el informe debe seguir siendo exacto. |
| Numerador ASR-11 | `GET /v1/metricas` **después** de drenar el reportero | Locust no ve el JSONL. El reporte es *fire-and-forget*. |
| Denominador ASR-11 | `fallos_efectivos`, no `enviadas` | `factor_skip` en clase ocupacional 1 no altera la prima (el factor ya es `1.00`). Contar esas requests hace fallar ASR-11 por metodología, no por la táctica. |
| UI | Solo depuración (`locust` sin `--headless`) | La corrida oficial es headless, reproducible, sin operador. |
| `carga.py` | Se retira en L4, no antes | Hasta que Locust emita el mismo JSON, `correr.sh` no se toca. |
| Forma de carga (rampa/pico/bajada) | **Fuera de esta entrega** | El ASR pide pico sostenido. Una `LoadTestShape` es un experimento aparte. |

---

## 1. Qué se mide y qué no

### Hipótesis (no cambian)

| ASR | Hipótesis | Umbral |
|---|---|---|
| **ASR-11** | El sistema identifica el cálculo erróneo **antes** de entregarlo al canal, en horario pico | ≥ 99 % de los fallos **efectivamente inyectados**, en **todos** los modos |
| **ASR-12** | Con un cotizador fallando, el cliente recibe el valor correcto y el journey no se encarece | retardo total añadido `media(C) − media(A) ≤ 300 ms` **y** `primas_erroneas == 0` |

### Reparto de responsabilidades

```text
inyectar.sh          estímulo de FALLO (FAULT_MODE en una réplica)
locustfile.py        estímulo de CARGA (horario pico) + oráculo de prima
/v1/metricas         numerador de detección (JSONL ya persistido)
correr.sh            las tres corridas, el drenaje del reportero, la tasa
reporte.py           veredicto Markdown; ningún número a mano
```

Locust **no** inyecta fallos, **no** lee Redis y **no** decide si la hipótesis
se cumple.

### Contrato JSON que Locust debe emitir

Mismo esquema que escribe hoy `carga.py`, más un campo. `reporte.py` y el
bloque de `correr.sh` que calcula `tasa_deteccion` dependen de él.

```json
{
  "etiqueta": "deteccion-premium_offset",
  "enviadas": 1000,
  "duracion_s": 120.1,
  "tasa_real_por_minuto": 499.6,
  "por_http": {"200": 1000},
  "por_estado_cotizacion": {"COTIZADO": 1000},
  "alcanzaron_votacion": 1000,
  "fallos_efectivos": 1000,
  "latencia_ms": {
    "n": 1000,
    "media": 8.1,
    "p50": 7.9,
    "p99": 12.49,
    "max": 22.26
  },
  "primas_erroneas": 0,
  "muestras_erroneas": []
}
```

`alcanzaron_votacion` sigue siendo las HTTP distintas de `0` (sin conexión).
Un `503`/`504` **sí** llegó a Votación y cuenta. `fallos_efectivos` es el
subconjunto en el que el modo inyectado realmente produce un resultado
distinto o una réplica ausente; es el denominador de ASR-11.

---

## 2. Diseño del locustfile

### Estructura objetivo

```
scripts/experiment/
├── locustfile.py                 # único punto de entrada de `locust -f`
├── carga.py                      # se borra en L4
├── locust_carga/                 # importable por pytest y por locustfile
│   ├── __init__.py
│   ├── solicitudes.py            # solicitud_de(indice) — se mueve desde carga.py
│   ├── oraculo.py                # prima esperada a partir de emitido_en
│   ├── prediccion.py             # ¿este (solicitud, modo) produce fallo efectivo?
│   ├── metricas_run.py           # acumuladores gevent-safe + resumen JSON
│   └── percentil.py              # el mismo percentil de carga.py
├── requirements.txt              # locust pinneado
├── inyectar.sh                   # sin cambios
├── correr.sh                     # L4: invoca locust --headless
├── _metricas.py                  # sin cambios
├── reporte.py                    # L4: usa fallos_efectivos en la tabla
└── experiment_common/            # oráculo de dominio, sin cambios
```

`locustfile.py` se queda delgado: clase `CotizadorUser`, listeners
`test_start` / `test_stop`, y nada de fórmula actuarial.

### Usuario virtual

```python
class CotizadorUser(HttpUser):
    wait_time = constant_pacing(1.2)   # 10 users → 8.33 RPS = 500/min

    @task
    def cotizar(self) -> None:
        ...
```

Cada request:

1. Toma el siguiente `indice` atómico (gevent-safe).
2. Construye `solicitud_de(indice, hoy)` — idéntica a la de `carga.py`.
3. `POST /v1/cotizaciones` con `catch_response=True` y `timeout=5`.
4. Si HTTP 200: compara `cotizacion.prima_mensual` con el oráculo, usando la
   fecha de `emitido_en` (no el reloj local: cruzar medianoche UTC marcaría
   como errónea una prima correcta).
5. Si la prima no coincide: `response.failure("prima errónea")` y se incrementa
   `primas_erroneas`.
6. Acumula latencia cruda (`response_time` del evento, en ms float), estado
   HTTP, estado de cotización, y si el par `(solicitud, FAULT_MODE)` es un
   fallo efectivo.

Variables de entorno del locustfile (las pone `correr.sh`, no Docker):

| Variable | Default | Uso |
|---|---|---|
| `LOCUST_ETIQUETA` | (requerida) | `baseline`, `deteccion-premium_offset`, … |
| `LOCUST_SALIDA` | (requerida) | JSON de la corrida |
| `LOCUST_MODO` | `none` | Modo inyectado en B; alimenta `prediccion.py` |
| `LOCUST_HOST` | `--host` | `http://localhost:8000` |

El número de requests lo fija `--run-time` **o** un tope `LOCUST_N`. Para no
cambiar el diseño de F7 (N fijas, no duración), Locust se detiene al llegar a
`n` requests (`environment.runner.quit()` cuando el contador atómico alcanza
`n`). Así `RAPIDO=1` sigue siendo `N_BASE=200` y no “corre 10 minutos”.

### Predicción de fallo efectivo

No se duplica `faults.py`. Se predice con el tarifario que el oráculo ya tiene:

| Modo | Fallo efectivo cuando |
|---|---|
| `none` | nunca (corrida A; `fallos_efectivos = 0`) |
| `premium_offset` | siempre (× 1.15) |
| `rounding_drift` | siempre (trunca a pesos) |
| `out_of_range` | siempre (× 500) |
| `silent_zero` | siempre |
| `factor_skip` | `clase_ocupacional != 1` (clase 1 ya vale `1.00`) |
| `rate_table_stale` | `calcular(..., tabla_anterior) != calcular(..., vigente)` |
| `slow`, `crash` | siempre (la réplica no aporta resultado a tiempo) |

`rate_table_stale` se resuelve con el oráculo, no a ojo: las tasas de
`2025.11` y `2026.02` difieren en todos los tramos hoy, pero si alguien
igualara un tramo mañana la predicción seguiría siendo correcta.

### Drenaje del reportero

Votación reporta incidentes en un `ThreadPoolExecutor` **después** de
responder al cliente (`timeout_reporte_s = 2`). Si `correr.sh` lee
`/v1/metricas` en el mismo instante en que Locust termina, ASR-11 sale
subestimada por una carrera.

Después de cada corrida B, antes de leer el numerador:

```
esperar hasta que GET /v1/metricas .total deje de crecer
durante 500 ms, o 5 s máximo
```

No es un `sleep 2` ciego: un silencio de medio segundo en el JSONL basta
porque cada `anexar` hace `flush`.

---

## 3. Fases de implementación

## L0 · Andamiaje

**Objetivo:** Locust instalado en el venv del monorepo, sin tocar imágenes ni
el compose.

**Pasos**

1. Crear `scripts/experiment/requirements.txt` con Locust pinneado a una
   versión que instale limpio en Python 3.14 (comprobar en L0, no adivinar el
   tag). Nada más: el oráculo ya está en el árbol.
2. Añadir en `scripts/bootstrap.sh`, después de pytest:

   ```bash
   python -m pip install --quiet -r scripts/experiment/requirements.txt
   ```

3. Crear el paquete vacío `scripts/experiment/locust_carga/`.
4. Añadir `scripts/experiment` a `pyproject.toml` → `[tool.pytest.ini_options] testpaths`
   **o** un `conftest` local invocado con `pytest scripts/experiment`. Preferir
   ampliar `testpaths` para que `scripts/test.sh` cubra el generador.
5. Añadir `scripts/experiment/resultados/` al `.gitignore` si no está (JSON de
   corrida; no se commitean).

**Validación**

```bash
source .venv/bin/activate
python -m pip install -r scripts/experiment/requirements.txt
locust --version
python -c "from locust import HttpUser, constant_pacing"
```

**Resultado esperado:** Locust importa; ningún `Dockerfile` ni
`docker-compose.yaml` de servicio cambia; `docker compose config` sigue
válido.

---

## L1 · Usuario y ritmo

**Objetivo:** 10 usuarios a 500/min contra el gateway, sin oráculo todavía.
Demuestra que el instrumento produce el estímulo del ASR, no que las
hipótesis se cumplen.

**Pasos**

1. Mover `solicitud_de` y las tablas `CANALES`/`SUMAS`/`PLAZOS`/`CLASES`/`EDADES`
   a `locust_carga/solicitudes.py` **sin cambiar un byte de la función**.
   `carga.py` pasa a importarla, para no tener dos generadores durante L1–L3.
2. `locustfile.py` con `CotizadorUser`, `constant_pacing(1.2)`, un único
   `@task` que hace POST y marca `failure` si el status no es 2xx/3xx/4xx/5xx
   (cualquier respuesta HTTP cuenta; solo falla la excepción de red).
3. Tope `LOCUST_N`: al llegar a N requests, `environment.runner.quit()`.
4. Prueba unitaria: `solicitud_de(0, date(2026, 8, 31))` es estable;
   `solicitud_de(i)` recorre las cuatro clases ocupacionales.

**Validación**

```bash
./scripts/up.sh                         # stack sano, FAULT_*=none
LOCUST_N=50 LOCUST_ETIQUETA=smoke LOCUST_SALIDA=/tmp/smoke.json \
  locust -f scripts/experiment/locustfile.py --headless \
         --users 10 --spawn-rate 10 \
         --host http://localhost:8000
```

**Resultado esperado:** ~50 POST en ~6 s (50 / 8.33 ≈ 6 s), tasa real cercana
a 500/min, mayoría HTTP 200, prima de la solicitud-ejemplo alcanzable a mano
con `scripts/api-calls/cotizar.sh`. Si la tasa real se dispara sobre 600/min,
el pacing no está aplicado (síntoma típico: `wait_time` olvidado o `on_start`
haciendo el POST).

---

## L2 · Oráculo y métricas de ASR-12

**Objetivo:** cada 200 se verifica contra el dominio; el JSON de salida trae
la latencia media cruda y `primas_erroneas`.

**Pasos**

1. `locust_carga/oraculo.py`: `prima_esperada(cuerpo, solicitud) -> Decimal`,
   copiando `_esperada` de `carga.py` (fecha desde `emitido_en`).
2. `locust_carga/percentil.py`: la misma función `percentil` de `carga.py`
   (ordenados, índice `int(n*q)`). No usar `statistics.quantiles` ni el
   histograma de Locust: el informe tiene que ser comparable con la corrida
   ya publicada en `docs/RESULTADOS-EXPERIMENTO.md`.
3. `locust_carga/metricas_run.py`: contadores protegidos con `gevent.lock.Semaphore`
   o un único greenlet dueño del estado. Campos: latencias de 200, primas
   erróneas (máx. 5 muestras), histogramas HTTP y de `estado`.
4. Listener `test_stop`: escribe el JSON del §1. Hasta L3,
   `fallos_efectivos = alcanzaron_votacion` si `LOCUST_MODO != none`, else 0.
5. Pruebas: oráculo sobre `docs/ejemplos/solicitud.json` → `90348.41` con
   fecha `2026-08-31`; una prima distinta marca `erronea=True`.

**Validación**

```bash
# línea base corta
LOCUST_N=200 LOCUST_ETIQUETA=baseline LOCUST_MODO=none \
LOCUST_SALIDA=scripts/experiment/resultados/A-baseline.json \
  locust -f scripts/experiment/locustfile.py --headless \
         --users 10 --spawn-rate 10 --host http://localhost:8000
python -c "import json; d=json.load(open('scripts/experiment/resultados/A-baseline.json')); \
print(d['primas_erroneas'], d['latencia_ms']['media'], d['tasa_real_por_minuto'])"

# con fallo, el oráculo debe seguir viendo la prima SANA
./scripts/experiment/inyectar.sh b premium_offset
LOCUST_N=50 LOCUST_ETIQUETA=oraculo LOCUST_MODO=premium_offset \
LOCUST_SALIDA=/tmp/oraculo.json \
  locust -f scripts/experiment/locustfile.py --headless \
         --users 10 --spawn-rate 10 --host http://localhost:8000
python -c "import json; print(json.load(open('/tmp/oraculo.json'))['primas_erroneas'])"
./scripts/experiment/inyectar.sh b none
```

**Resultado esperado:** corrida sana → `primas_erroneas = 0`, latencia media del orden
de 10 ms (no 300). Con `premium_offset` en B → `primas_erroneas = 0` (ASR-12:
Votación enmascara). Si aquí aparecen primas erróneas, el sistema está roto y
no se avanza: Locust no se “ajusta” para esconderlo.

---

## L3 · Denominador de ASR-11

**Objetivo:** que la tasa de detección no cuente requests en las que el modo
no inyectó un error observable.

**Pasos**

1. `locust_carga/prediccion.py` con la tabla del §2. Para `rate_table_stale`
   compara dos llamadas al oráculo (tabla vigente vs `2025.11`). Para
   `factor_skip`, `clase_ocupacional != 1`. Para `slow`/`crash`, siempre
   efectivo. **No** importar `cotizador.faults`: el generador no depende del
   código de un servicio.
2. Cada task incrementa `fallos_efectivos` solo si la predicción es verdadera
   **y** la request alcanzó Votación.
3. Pruebas parametrizadas, sin Docker:

   | solicitud | modo | efectivo |
   |---|---|---|
   | clase 1 | `factor_skip` | no |
   | clase 2 | `factor_skip` | sí |
   | cualquiera | `premium_offset` | sí |
   | cualquiera | `none` | no |
   | cualquiera | `crash` | sí |

4. Helper `esperar_metricas_estables()` en un módulo pequeño usado por
   `correr.sh` (Python de 10 líneas, no bash + `sleep`).

**Validación**

```bash
python -m pytest scripts/experiment -q
./scripts/experiment/inyectar.sh b factor_skip
# 12 requests recorren las 4 clases × 3 veces → 9 efectivos (clases 2,3,4)
LOCUST_N=12 LOCUST_MODO=factor_skip ...
python -c "import json; print(json.load(open('...'))['fallos_efectivos'])"
./scripts/experiment/inyectar.sh b none
```

**Resultado esperado:** pruebas verdes; JSON con `fallos_efectivos == 9` para
12 requests bajo `factor_skip` (el ciclo de `solicitud_de` usa
`(indice * 5) % 4` sobre `[1,2,3,4]`, que recorre las cuatro clases a partes
iguales). Ese 75 % que hoy sale en `RESULTADOS-EXPERIMENTO.md` queda
explicado: 3/12 no eran fallos.

---

## L4 · Orquestación

**Objetivo:** `correr.sh` produce el mismo informe de siempre, con Locust
como generador y el denominador corregido.

**Pasos**

1. Extraer de `carga.py` lo que aún no se haya movido; borrar `carga.py`.
2. En `correr.sh`, sustituir:

   ```bash
   CARGA="python scripts/experiment/carga.py"
   $CARGA --etiqueta baseline --n "$N_BASE" --por-minuto "$POR_MINUTO" \
          --salida "$RES/A-baseline.json"
   ```

   por una función:

   ```bash
   carga() {  # etiqueta, n, salida, modo
     LOCUST_ETIQUETA="$1" LOCUST_N="$2" LOCUST_SALIDA="$3" LOCUST_MODO="${4:-none}" \
       locust -f scripts/experiment/locustfile.py --headless \
              --users 10 --spawn-rate 10 \
              --host "http://localhost:${PUERTO_GATEWAY:-8000}" \
              --only-summary
   }
   ```

3. Tras cada modo de la corrida B: `esperar_metricas_estables`, luego el
   mismo bloque Python que hoy escribe `modo`, `incidentes_registrados` y
   `tasa_deteccion`, pero:

   ```python
   den = datos["fallos_efectivos"]   # ya no alcanzaron_votacion
   datos["tasa_deteccion"] = round((despues - antes) / den, 4) if den else 0.0
   ```

   Conservar `alcanzaron_votacion` en el JSON: sirve para auditar cuántas
   requests no fueron fallo efectivo.
4. `reporte.py`: en la tabla de ASR-11, la columna “Cotizaciones” pasa a
   mostrar `fallos_efectivos` (el denominador real). Añadir una nota bajo la
   tabla cuando `fallos_efectivos < alcanzaron_votacion` (el caso
   `factor_skip`). Los umbrales `0.99` y `300` no se tocan.
5. `PLAN-IMPLEMENTACION.md` §F7 paso 2: una línea que apunte a este
   documento y a `locustfile.py`, en lugar de `carga.js`.

**Validación**

```bash
RAPIDO=1 ./scripts/experiment/correr.sh
```

**Resultado esperado:**

- Existen `A-baseline.json`, `B-<modo>.json` × 8, `C-enmascaramiento.json`.
- `docs/RESULTADOS-EXPERIMENTO.md` regenerado, ningún número a mano.
- ASR-12: retardo añadido del orden de milisegundos, `primas_erroneas = 0`,
  veredicto **CUMPLE**.
- ASR-11: `factor_skip` deja de aparecer al 75 % **si** los efectivos se
  detectaron; el veredicto sale de `min(tasa por modo) ≥ 0.99`.
- Duración de `RAPIDO=1` similar a la actual (~2–3 min de carga + reinicios
  de réplica), no 38 min.

Si ASR-11 sigue bajo 99 % en un modo que **sí** inyecta fallo (p. ej. `slow`
por la ventana de gracia), eso es resultado del sistema, no un bug del
generador. Se documenta, no se “corrige” Locust.

---

## L5 · Corrida oficial

**Objetivo:** los números que se entregan como evidencia del experimento.

**Pasos**

1. Stack limpio: `./scripts/down.sh && ./scripts/up.sh`.
2. Réplicas en `none`, JSONL vacío (ya lo hace `correr.sh`).
3. `./scripts/experiment/correr.sh` **sin** `RAPIDO` → 5000 + 8×1000 + 5000 a
   500/min (~38 min de carga, más reinicios).
4. No tocar los JSON de `resultados/` a mano. Si hay que repetir un modo,
   se repite la corrida entera: la media de A y C tiene que nacer del mismo
   proceso para ser comparables.
5. Commitear `docs/RESULTADOS-EXPERIMENTO.md` (el informe) , no los JSON
   crudos salvo que el curso pida el artefacto.

**Validación y criterio de aceptación** (idéntico a F7, con el denominador
corregido)

| ASR | Métrica | Umbral | Cómo se obtiene |
|---|---|---|---|
| **ASR-11** | Tasa de detección | **≥ 99 %** | incidentes ÷ `fallos_efectivos`, por modo |
| **ASR-12** | Retardo total añadido | **≤ 300 ms** | `media(C) − media(A)` |
| **ASR-12** | Primas erróneas | **0** | oráculo Locust, una a una |

**Resultado esperado:** informe generado por `reporte.py`; límite conocido
del diseño (réplicas idénticas, fallo sistemático invisible a la votación)
sigue escrito. Locust no añade un veredicto propio.

---

## 4. Qué no se hace en esta entrega

1. **`LoadTestShape` de rampa.** Útil para preguntar “¿hasta cuántos RPS
   aguanta el presupuesto de 250 ms?”, que es otra hipótesis. El ASR pide
   horario pico sostenido a 500/min.
2. **Locust distribuido** (master/workers). 8.33 RPS cabe en un proceso.
3. **Meter Locust en Docker Compose.** Metería al generador en la red
   `edge` y mezclaría el instrumento con el sistema medido.
4. **Leer `consenso.divergencia_detectada` como numerador oficial.** Con
   `EXPOSE_CONSENSUS=true` puede loguearse como **triangulación** (si el
   JSONL y la respuesta no coinciden, el reportero perdió incidentes). El
   numerador del ASR sigue siendo Gestión de Errores.
5. **Reescribir pytest de los servicios.** Los 193 tests unitarios cubren la
   táctica en aislamiento. Locust cubre el modo de operación del ASR.

---

## 5. Riesgos de esta pieza (no del sistema)

1. **Gevent y el oráculo.** `Decimal` en el greenlet del usuario bloquea el
   event loop. A 8 RPS el cálculo es despreciable. Si alguien sube a miles
   de RPS, el oráculo tiene que precomputarse o ir a un thread pool; no es
   el caso.
2. **`--users` demasiado alto.** 50 usuarios con `constant_pacing(1.2)` son
   2500/min y ya no se está midiendo el pico del ASR, se está saturando
   Redis. El número 10 es parte del protocolo, no un default de Locust.
3. **UI abierta durante la corrida oficial.** Un operador subiendo usuarios
   a mano invalida A vs C. Headless o nada.
4. **No drenar el reportero.** Falso negativo de ASR-11, atribuible al
   instrumento.
5. **Denominador 0.** Un modo que no produzca ningún fallo efectivo (p. ej.
   si se inyectara `factor_skip` solo con clase 1) no puede reportar tasa.
   `correr.sh` debe fallar ruidoso, no imprimir 0.00 %.

---

## 6. Comandos de referencia (después de L4)

```bash
# depurar con UI, 10 usuarios, pico 500/min
locust -f scripts/experiment/locustfile.py --host http://localhost:8000
# abrir http://localhost:8089  →  10 users, spawn 10

# smoke
RAPIDO=1 ./scripts/experiment/correr.sh

# evidencia
./scripts/experiment/correr.sh
```
