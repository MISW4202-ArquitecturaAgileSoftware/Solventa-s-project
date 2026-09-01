# Resultados del experimento — detección y enmascaramiento

Generado por `scripts/experiment/reporte.py` a partir de los JSON de
`scripts/experiment/resultados/`. Ningún número de este documento se
escribe a mano.

Fecha de la corrida: 2026-09-01T03:15:34+00:00

---

## ASR-11 · Detección de un cálculo erróneo de prima

Umbral: **≥ 99 %** de los cálculos erróneos inyectados, detectados.

| Modo de fallo | Vía de detección esperada | Cotizaciones | Incidentes | Tasa |
|---|---|---:|---:|---:|
| `crash` | réplica no responde | 100 | 100 | 100.00 % |
| `factor_skip` | divergencia de hash | 100 | 75 | 75.00 % |
| `out_of_range` | regla de validez | 100 | 100 | 100.00 % |
| `premium_offset` | divergencia de hash | 100 | 100 | 100.00 % |
| `rate_table_stale` | regla de validez | 100 | 100 | 100.00 % |
| `rounding_drift` | divergencia de hash | 100 | 100 | 100.00 % |
| `silent_zero` | regla de validez | 100 | 100 | 100.00 % |
| `slow` | réplica no responde | 100 | 100 | 100.00 % |

- Tasa global: **96.88 %** (775/800).
- Peor modo: **75.00 %**.
- Veredicto: **NO CUMPLE** (umbral 99 % en TODOS los modos).

## ASR-12 · Enmascaramiento del cálculo erróneo

Umbrales: retardo añadido **≤ 300 ms** sobre el p95 de la línea base, y
**0 primas erróneas** entregadas.

| Corrida | n | tasa real | p50 | p95 | p99 | máx |
|---|---:|---:|---:|---:|---:|---:|
| A · línea base | 200 | 1205.0/min | 7.51 ms | 9.09 ms | 10.5 ms | 21.08 ms |
| C · con fallo activo | 200 | 1204.8/min | 7.9 ms | 10.35 ms | 12.49 ms | 22.26 ms |

- Retardo añadido sobre el p95: **+1.26 ms** (base 9.09 ms → con fallo 10.35 ms).
- Veredicto latencia: **CUMPLE** (umbral ≤ 300 ms).

- Primas erróneas entregadas en la corrida C: **0** de 200 respuestas verificadas una a una contra el dominio.
- Veredicto integridad: **CUMPLE** (umbral: 0).

- Estados devueltos en la corrida C: `{'COTIZADO': 200}`.

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
