# Resultados del experimento — detección y enmascaramiento

Generado por `scripts/experiment/reporte.py` a partir de los JSON de
`scripts/experiment/resultados/`. Ningún número de este documento se
escribe a mano.

Fecha de la corrida: 2026-09-03T02:28:37+00:00

---

## ASR-11 · Detección de un cálculo erróneo de prima

Umbral: **≥ 99 %** de los cálculos erróneos inyectados, detectados.

| Modo de fallo | Vía de detección esperada | Cotizaciones | Incidentes | Tasa |
|---|---|---:|---:|---:|
| `crash` | réplica no responde | 1000 | 1000 | 100.00 % |
| `factor_skip` | divergencia de resultado | 750 | 750 | 100.00 % |
| `out_of_range` | divergencia de resultado | 1000 | 1000 | 100.00 % |
| `premium_offset` | divergencia de resultado | 1000 | 1000 | 100.00 % |
| `rate_table_stale` | divergencia de resultado | 1000 | 1000 | 100.00 % |
| `rounding_drift` | divergencia de resultado | 1000 | 1000 | 100.00 % |
| `silent_zero` | divergencia de resultado | 1000 | 1000 | 100.00 % |
| `slow` | réplica no responde | 1000 | 1000 | 100.00 % |

- Tasa global: **100.00 %** (7750/7750).
- Peor modo: **100.00 %**.
- Veredicto: **CUMPLE** (umbral 99 % en TODOS los modos).

- `factor_skip`: 750 fallos efectivos de 1000 requests que alcanzaron Votación (el modo no altera todas las solicitudes).

## ASR-12 · Enmascaramiento del cálculo erróneo

Umbrales: retardo añadido **≤ 300 ms** sobre el p95 de la línea base, y
**0 primas erróneas** entregadas.

| Corrida | n | tasa real | p50 | p95 | p99 | máx |
|---|---:|---:|---:|---:|---:|---:|
| A · línea base | 5000 | 476.3/min | 62.38 ms | 89.36 ms | 97.89 ms | 111.0 ms |
| C · con fallo activo | 5000 | 476.3/min | 71.05 ms | 97.79 ms | 106.03 ms | 118.45 ms |

- Retardo añadido sobre el p95: **+8.43 ms** (base 89.36 ms → con fallo 97.79 ms).
- Veredicto latencia: **CUMPLE** (umbral ≤ 300 ms).

- Primas erróneas entregadas en la corrida C: **0** de 5000 respuestas verificadas una a una contra el dominio.
- Veredicto integridad: **CUMPLE** (umbral: 0).

- Estados devueltos en la corrida C: `{'COTIZADO': 5000}`.

---

## Límite conocido del diseño

Las tres réplicas ejecutan el **mismo código**. La votación detecta
fallos *no correlacionados*: un error en una réplica, o en dos con
modos distintos. Un error **sistemático** en la fórmula o en el
tarifario produciría tres resultados idénticos y erróneos, y la
votación reportaría consenso sobre el valor equivocado sin registrar
incidente alguno.

Detectar eso exigiría N-version programming real —tres
implementaciones independientes del cálculo bajo el mismo contrato—,
que se descartó por coste. Las reglas de validez de §2.4 cubren
parcialmente el hueco: atrapan el resultado estructuralmente imposible
aunque las tres réplicas coincidan, pero no un desvío plausible.
