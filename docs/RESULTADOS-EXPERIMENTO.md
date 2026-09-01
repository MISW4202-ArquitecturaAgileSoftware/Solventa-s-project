# Resultados del experimento — detección y enmascaramiento

Generado por `scripts/experiment/reporte.py` a partir de los JSON de
`scripts/experiment/resultados/`. Ningún número de este documento se
escribe a mano.

Fecha de la corrida: 2026-09-01T04:18:58+00:00

---

## ASR-11 · Detección de un cálculo erróneo de prima

Umbral: **≥ 99 %** de los cálculos erróneos inyectados, detectados.

El denominador son los **cálculos erróneos inyectados**, no las
cotizaciones enviadas. Un modo de fallo puede ser neutro para ciertas
entradas: `factor_skip` omite el factor de clase ocupacional, que para
la clase 1 ya vale `1.00`, así que en esas solicitudes la réplica
averiada calcula el valor correcto y no hay error que detectar. Cada
detección se atribuye a su journey cruzando por `correlation_id`, de
modo que un incidente ajeno al fallo inyectado no puede inflar la tasa.

| Modo de fallo | Vía de detección esperada | Cotizaciones | Neutras | Errores inyectados | Detectados | Tasa |
|---|---|---:|---:|---:|---:|---:|
| `crash` | réplica no responde | 1000 | 0 | 1000 | 1000 | 100.00 % |
| `factor_skip` | divergencia de hash | 1000 | 250 | 750 | 750 | 100.00 % |
| `out_of_range` | regla de validez | 1000 | 0 | 1000 | 1000 | 100.00 % |
| `premium_offset` | divergencia de hash | 1000 | 0 | 1000 | 1000 | 100.00 % |
| `rate_table_stale` | regla de validez | 1000 | 0 | 1000 | 1000 | 100.00 % |
| `rounding_drift` | divergencia de hash | 1000 | 0 | 1000 | 1000 | 100.00 % |
| `silent_zero` | regla de validez | 1000 | 0 | 1000 | 1000 | 100.00 % |
| `slow` | réplica no responde | 1000 | 0 | 1000 | 1000 | 100.00 % |

- Tasa global: **100.00 %** (7750/7750).
- Peor modo: **100.00 %**.
- Veredicto: **CUMPLE** (umbral 99 % en TODOS los modos).

## ASR-12 · Enmascaramiento del cálculo erróneo

Umbrales: retardo añadido **≤ 300 ms** sobre el p95 de la línea base, y
**0 primas erróneas** entregadas.

| Corrida | n | tasa real | p50 | p95 | p99 | máx |
|---|---:|---:|---:|---:|---:|---:|
| A · línea base | 5000 | 500.1/min | 8.56 ms | 10.56 ms | 13.33 ms | 23.82 ms |
| C · con fallo activo | 5000 | 500.1/min | 9.09 ms | 10.21 ms | 10.91 ms | 23.11 ms |

- Retardo añadido sobre el p95: **-0.35 ms** (base 10.56 ms → con fallo 10.21 ms).
- Veredicto latencia: **CUMPLE** (umbral ≤ 300 ms).

- Primas erróneas entregadas en la corrida C: **0** de 5000 respuestas verificadas una a una contra el dominio.
- Veredicto integridad: **CUMPLE** (umbral: 0).

- Estados devueltos en la corrida C: `{'COTIZADO': 5000}`.

## Observación de disponibilidad (fuera del alcance de ASR-11/12)

Todas las cotizaciones obtuvieron respuesta de éxito.

---

## Límites conocidos del diseño

### Coste de la política de quórum

Con quórum 2 de 3, si una réplica sana no responde dentro del
presupuesto **mientras otra está averiada**, quedan dos respuestas que
no coinciden: no hay mayoría y el sistema devuelve 503 en vez de
adivinar. Rechazar es preferible a entregar un valor sin confirmar,
pero conviene tenerlo escrito: la disponibilidad del journey depende de
que al menos dos réplicas respondan a tiempo, no solo de que el cálculo
sea correcto.

Es un suceso raro y transitorio —una corrida previa de este mismo
experimento lo observó 3 veces en 18.000 cotizaciones (0,017 %), y la
corrida definitiva ninguna—, así que la tabla de arriba puede no
mostrarlo. No depende del modo de fallo inyectado, sino de una pausa
puntual en una réplica sana.

### Fallos correlacionados

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
