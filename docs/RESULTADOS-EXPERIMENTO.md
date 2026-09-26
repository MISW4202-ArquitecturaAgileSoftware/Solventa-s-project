# Resultados del experimento — Solventa (ASR-23 / ASR-31)

- Fecha: 2026-09-25T03:38:47Z
- `PERIODO_AUDITORIA_S` evaluados: 2, 5, 10
- Repeticiones por periodo: 5
- Corridas totales: 15
- Imágenes:
  - `redis`: `8.10-alpine`
  - `solventa/api-gateway`: `dev`
  - `solventa/auditor`: `dev`
  - `solventa/autenticacion`: `dev`
  - `solventa/gestion-cotizador`: `dev`
  - `solventa/gestion-polizas`: `dev`
  - `solventa/validacion`: `dev`

## Criterios de aceptación

| Métrica | Umbral | Valor observado | Cumple |
|---|---|---|---|
| ASR-23 · detección de OTP fallidos | 100 % | 100% | sí |
| ASR-23 · operaciones privilegiadas ejecutadas sin OTP correcto | 0 | 0 | sí |
| ASR-23 · segunda operación bloqueada | 100 % | 100% | sí |
| ASR-23 · latencia de revocación (p50 / p95) | reportar | 143 ms / 149 ms | sí |
| ASR-31 · detección de consultas fuera de alcance | 100 % | 100% | sí |
| ASR-31 · falsos positivos (revocaciones en legítimos) | 0, con alerta CONSULTA_INUSUAL | 0 revocaciones; alerta inusual: sí | sí |
| ASR-31 · segunda consulta bloqueada (atacante lento: espera > P entre consultas) | 100 % | 100% | sí |
| ASR-31 · operaciones del atacante antes de cerrar la sesión | 0 | 528 | NO |
| Alertas registradas duplicadas (ambos ASR) | 0 | 0 | sí |
| Eventos de seguridad redundantes absorbidos por idempotencia | reportar | 2717 | sí |

### Qué mide cada criterio

- **ASR-23 · detección de OTP fallidos.** El atacante eleva su rol a supervisor y envía el código 000000. Cada intento debe dejar una alerta OTP_FALLIDO de esa misma sesión. El porcentaje es cuántos intentos quedaron registrados.
- **ASR-23 · operaciones privilegiadas ejecutadas sin OTP correcto.** La aprobación se retiene hasta recibir el código. El número cuenta pólizas del atacante que no siguieron PENDIENTE: con el umbral en 0, ninguna aprobación se ejecutó sin el OTP real.
- **ASR-23 · segunda operación bloqueada.** Después del código rechazado, el atacante vuelve a pedir la aprobación. Debe recibir 401 sesion-revocada. El porcentaje es en cuántas repeticiones esa segunda operación quedó bloqueada.
- **ASR-23 · latencia de revocación (p50 / p95).** Milisegundos entre el 403 del código inválido y el primer 401. No hay umbral de aprobado o reprobado: mide el tiempo que tarda la reacción asíncrona en cerrar la sesión.
- **ASR-31 · detección de consultas fuera de alcance.** Un asesor de norte consulta una póliza del sur. El auditor debe avisar a Validación y quedar una alerta ALCANCE_NO_AUTORIZADO de esa sesión. El porcentaje es en cuántas repeticiones se detectó.
- **ASR-31 · falsos positivos (revocaciones en legítimos).** El empleado que aprueba con el OTP real, y el asesor mixto que consulta centro (autorizado, pero fuera de su historial), no deben perder la sesión. El mixto sí debe generar la alerta CONSULTA_INUSUAL.
- **ASR-31 · segunda consulta bloqueada (atacante lento: espera > P entre consultas).** El atacante consulta el sur, espera más de un periodo de auditoría y consulta otra vez. La segunda respuesta debe ser 401 sesion-revocada. Que esa segunda llegue bloqueada no borra la consulta que sí se sirvió antes: esa cuenta en el criterio siguiente.
- **ASR-31 · operaciones del atacante antes de cerrar la sesión.** Cada respuesta 200 del atacante de ASR-31, en la consulta lenta y en la ráfaga, es una póliza entregada con la sesión todavía abierta. El criterio solo se cumple si ese conteo es 0. Si hay un 200 antes del 401, no se cumple: se le permitió operar antes de cerrarle la sesión.
- **Alertas registradas duplicadas (ambos ASR).** Cuenta alertas guardadas que repiten el mismo par sesión y motivo. El umbral es 0: Reacción conserva una sola alerta por incidente, aunque lleguen varios eventos de la misma sesión.
- **Eventos de seguridad redundantes absorbidos por idempotencia.** Líneas alerta_duplicada en el log de Validación. Cada consulta de la ráfaga, antes del 401, genera otro evento del mismo incidente; Reacción lo descarta. Se informa el total, sin exigirle un tope.

## Ventana de exposición por `PERIODO_AUDITORIA_S`

Ráfaga concurrente de `locustfile.py` (`AtacanteRafagaASR31`): cinco atacantes con sesión legítima y alcance `norte` consultan pólizas de `sur` en bucle (una petición, 100 ms de espera, otra petición). Cada fila agrega 5 atacantes × N repeticiones. La **ventana de exposición** es el tiempo entre la primera consulta de un atacante y su primer `401 sesion-revocada`; **consultas 200 antes del bloqueo** es cuántas pólizas ajenas le fueron efectivamente entregadas en ese intervalo (promedio por atacante, con el mínimo y el máximo observados).

| Periodo (s) | Muestras | Ventana min (ms) | p50 (ms) | p95 (ms) | max (ms) | Intervalo entre consultas (ms) | Consultas 200 antes del bloqueo (min / media / max) |
|---|---|---|---|---|---|---|---|
| 2 | 25 | 714 | 863 | 995 | 1049 | 121 | 6 / 7.2 / 9 |
| 5 | 25 | 3660 | 3878 | 4088 | 4110 | 121 | 30 / 32.2 / 34 |
| 10 | 25 | 8738 | 8927 | 9011 | 9024 | 123 | 70 / 72.3 / 74 |

### Cómo leer la ventana

- La columna de consultas es la ventana dividida por el ritmo del atacante (`consultas ≈ ventana / intervalo + 1`). Esas respuestas `200` anteriores al `401` son operaciones servidas con la sesión abierta: el criterio de aceptación correspondiente exige que sean 0, y no se cumple mientras el conteo sea mayor.
- La ventana se descompone en (a) el tiempo hasta el siguiente ciclo del Auditor, gobernado por `PERIODO_AUDITORIA_S`; (b) la cadena Auditor → Validación → `seguridad` → Reacción (hilo interno de Validación) → Autenticación, de ~130 ms (coincide con la latencia de revocación de ASR-23); y (c) hasta una petición más del atacante, porque solo ve el `401` en su siguiente consulta.
- Los valores están agrupados cerca de `P − 1 s` y no de `P / 2` porque el protocolo es determinista: cada repetición reinicia el stack y los escenarios previos duran siempre lo mismo, así que la ráfaga arranca siempre poco después de un ciclo del Auditor. Es el peor momento para el sistema, de modo que las ventanas reportadas son **conservadoras, cercanas al peor caso** (`P + 0,13 s`); un atacante que llegara en un instante aleatorio del ciclo obtendría en promedio la mitad.
- Cada consulta servida durante la ventana genera su propio evento de auditoría, una anomalía y un evento de seguridad con el mismo par `(session_id, motivo)`. Reacción conserva una sola alerta por atacante y descarta el resto: ese es el conteo de eventos redundantes absorbidos de la tabla de criterios.

## Interpretación de ASR-31: dos lecturas de "impedir una segunda consulta"

| Lectura | Escenario que la mide | Resultado |
|---|---|---|
| Segunda consulta emitida **después** de que el Auditor haya corrido (atacante lento, espera más de `P` entre consultas) | `atacante_asr31_secuencial` | Bloqueada en el 100 % de las repeticiones |
| Segunda consulta **inmediata** (atacante rápido, el caso realista de exfiltración) | ráfaga concurrente de Locust | **No se impide**: se sirven todas las consultas hasta el siguiente ciclo del Auditor, ≈ `P × 9` por atacante al ritmo medido |

AAS-H710 declaraba como incertidumbre alta "comprobar que la reacción asíncrona revoque el acceso antes de una segunda solicitud, incluso con solicitudes concurrentes". El criterio de aceptación es más estricto que llegar a un `401` en la consulta siguiente: exige cero operaciones servidas antes de cerrar la sesión. Un `200` del atacante anterior a ese `401`, en la consulta lenta o en la ráfaga, es una póliza entregada con la sesión abierta y el criterio no se cumple. La detección a posteriori no puede frenar esa primera consulta —la región de la póliza solo se conoce al resolverla— ni las que lleguen antes del siguiente ciclo. El experimento cuantifica cuánto se fuga en función de `P`.

En contraste, ASR-23 sí se cumple estrictamente: la operación privilegiada se retiene antes de ejecutarse, mientras el OTP está pendiente se rechaza cualquier otra operación del rol nuevo, y el atacante no ejecuta ni una. Ahí la detección es síncrona y la reacción asíncrona solo añade los ~130 ms de cerrar la sesión.

## Conclusión

La detección se cumple en el 100 % de las repeticiones para ambos ASR, sin falsos positivos y sin alertas duplicadas, y la revocación asíncrona cuesta ~130 ms. En ASR-23 la operación privilegiada no se ejecuta. En ASR-31 el criterio de cero operaciones antes del cierre no se cumple cuando el atacante recibe un `200` antes del `401`: esa respuesta es una póliza ajena servida con la sesión abierta. Un atacante rápido obtiene cerca de nueve pólizas por cada segundo de `P`; la ventana crece de forma lineal con ese periodo.

Palancas de diseño que se derivan: reducir `P` acorta la ventana casi uno a uno pero no la elimina; limitar en Validación el ritmo de consultas por sesión acota la fuga por ventana con independencia de `P`; verificar el alcance de forma síncrona en Validación la eliminaría, al precio de acoplar Validación al dominio de pólizas (conocer la región de cada una), que es la decisión de arquitectura que habría que defender o rechazar.
