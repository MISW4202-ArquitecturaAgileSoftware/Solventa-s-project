# Resultados del experimento — Solventa (ASR-23 / ASR-31)

- Fecha: 2026-09-22T02:42:18Z
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
| ASR-23 · latencia de revocación (p50 / p95) | reportar | 132 ms / 148 ms | sí |
| ASR-31 · detección de consultas fuera de alcance | 100 % | 100% | sí |
| ASR-31 · falsos positivos (revocaciones en legítimos) | 0, con alerta CONSULTA_INUSUAL | 0 revocaciones; alerta inusual: sí | sí |
| ASR-31 · segunda consulta bloqueada (atacante lento: espera > P entre consultas) | 100 % | 100% | sí |
| Alertas registradas duplicadas (ambos ASR) | 0 | 0 | sí |
| Eventos de seguridad redundantes absorbidos por idempotencia | reportar | 3108 | sí |

## Ventana de exposición por `PERIODO_AUDITORIA_S`

Ráfaga concurrente de `locustfile.py` (`AtacanteRafagaASR31`): cinco atacantes con sesión legítima y alcance `norte` consultan pólizas de `sur` en bucle (una petición, 100 ms de espera, otra petición). Cada fila agrega 5 atacantes × N repeticiones. La **ventana de exposición** es el tiempo entre la primera consulta de un atacante y su primer `401 sesion-revocada`; **consultas 200 antes del bloqueo** es cuántas pólizas ajenas le fueron efectivamente entregadas en ese intervalo (promedio por atacante, con el mínimo y el máximo observados).

| Periodo (s) | Muestras | Ventana min (ms) | p50 (ms) | p95 (ms) | max (ms) | Intervalo entre consultas (ms) | Consultas 200 antes del bloqueo (min / media / max) |
|---|---|---|---|---|---|---|---|
| 2 | 25 | 798 | 1111 | 1317 | 1339 | 112 | 7 / 9.7 / 12 |
| 5 | 25 | 3821 | 4013 | 4155 | 4163 | 112 | 34 / 35.7 / 37 |
| 10 | 25 | 8862 | 9166 | 9795 | 9852 | 112 | 79 / 82.0 / 87 |

### Cómo leer la ventana

- La columna de consultas es la ventana dividida por el ritmo del atacante (`consultas ≈ ventana / intervalo + 1`). Todas las respuestas anteriores al `401` fueron `200`, y ninguna posterior: el corte es limpio y definitivo.
- La ventana se descompone en (a) el tiempo hasta el siguiente ciclo del Auditor, gobernado por `PERIODO_AUDITORIA_S`; (b) la cadena Auditor → Validación → `seguridad` → Reacción (hilo interno de Validación) → Autenticación, de ~130 ms (coincide con la latencia de revocación de ASR-23); y (c) hasta una petición más del atacante, porque solo ve el `401` en su siguiente consulta.
- Los valores están agrupados cerca de `P − 1 s` y no de `P / 2` porque el protocolo es determinista: cada repetición reinicia el stack y los escenarios previos duran siempre lo mismo, así que la ráfaga arranca siempre poco después de un ciclo del Auditor. Es el peor momento para el sistema, de modo que las ventanas reportadas son **conservadoras, cercanas al peor caso** (`P + 0,13 s`); un atacante que llegara en un instante aleatorio del ciclo obtendría en promedio la mitad.
- Cada consulta servida durante la ventana genera su propio evento de auditoría, una anomalía y un evento de seguridad con el mismo par `(session_id, motivo)`. Reacción conserva una sola alerta por atacante y descarta el resto: ese es el conteo de eventos redundantes absorbidos de la tabla de criterios.

## Interpretación de ASR-31: dos lecturas de "impedir una segunda consulta"

| Lectura | Escenario que la mide | Resultado |
|---|---|---|
| Segunda consulta emitida **después** de que el Auditor haya corrido (atacante lento, espera más de `P` entre consultas) | `atacante_asr31_secuencial` | Bloqueada en el 100 % de las repeticiones |
| Segunda consulta **inmediata** (atacante rápido, el caso realista de exfiltración) | ráfaga concurrente de Locust | **No se impide**: se sirven todas las consultas hasta el siguiente ciclo del Auditor, ≈ `P × 9` por atacante al ritmo medido |

AAS-H710 declaraba como incertidumbre alta "comprobar que la reacción asíncrona revoque el acceso antes de una segunda solicitud, incluso con solicitudes concurrentes". La respuesta empírica es que **no lo hace**: la detección a posteriori no puede frenar la primera consulta indebida —la región de la póliza solo se conoce al resolverla— ni ninguna de las que lleguen antes del siguiente ciclo. La arquitectura satisface ASR-31 frente a un atacante lento y **no lo satisface, tal como está redactado, frente a uno rápido**; el experimento cuantifica exactamente cuánto se fuga en función de `P`.

En contraste, ASR-23 sí se cumple estrictamente: la operación privilegiada se retiene antes de ejecutarse, mientras el OTP está pendiente se rechaza cualquier otra operación del rol nuevo, y el atacante no ejecuta ni una. Ahí la detección es síncrona y la reacción asíncrona solo añade los ~130 ms de cerrar la sesión.

## Conclusión

La detección se cumple en el 100 % de las repeticiones para ambos ASR, sin falsos positivos y sin alertas duplicadas, y la revocación asíncrona cuesta ~130 ms. El bloqueo de la segunda operación se cumple estrictamente en ASR-23 (detección síncrona) y solo condicionalmente en ASR-31 (detección a posteriori): un atacante que consulta rápido obtiene ≈ `P × 9` pólizas ajenas antes del primer `401`. Esa ventana de exposición es el coste medible del estilo asíncrono que la hipótesis de AAS-H710 ponía a prueba, y crece de forma lineal con `PERIODO_AUDITORIA_S`.

Palancas de diseño que se derivan: reducir `P` acorta la ventana casi uno a uno pero no la elimina; limitar en Validación el ritmo de consultas por sesión acota la fuga por ventana con independencia de `P`; verificar el alcance de forma síncrona en Validación la eliminaría, al precio de acoplar Validación al dominio de pólizas (conocer la región de cada una), que es la decisión de arquitectura que habría que defender o rechazar.
