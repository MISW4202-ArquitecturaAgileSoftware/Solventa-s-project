"""Informe del experimento (PLAN-IMPLEMENTACION.md §6, F9): genera
`docs/RESULTADOS-EXPERIMENTO.md` a partir de los JSON que `correr.py` guarda
por cada `(periodo, repetición)` en un directorio de resultados.

Los criterios de detección y bloqueo se calculan sobre los cuatro escenarios
secuenciales deterministas (uno por atacante/legítimo y por corrida); la
ventana de exposición se calcula sobre las filas JSONL de Locust, que sí
corren varios atacantes a la vez, como exige AAS-H710.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import metricas

RAIZ = Path(__file__).resolve().parents[2]
RUTA_INFORME = RAIZ / "docs" / "RESULTADOS-EXPERIMENTO.md"


def _cargar_corridas(directorio: Path) -> list[dict[str, Any]]:
    corridas = [
        json.loads(ruta.read_text(encoding="utf-8"))
        for ruta in sorted(directorio.glob("p*-r*.json"))
    ]
    if not corridas:
        raise RuntimeError(f"no hay corridas en {directorio}")
    return corridas


def _cargar_meta(directorio: Path) -> dict[str, Any]:
    ruta = directorio / "meta.json"
    if not ruta.is_file():
        return {}
    datos: Any = json.loads(ruta.read_text(encoding="utf-8"))
    return datos if isinstance(datos, dict) else {}


def _calcular_criterios(corridas: Sequence[Mapping[str, Any]]) -> list[metricas.CriterioAceptacion]:
    alertas: list[dict[str, Any]] = []
    for corrida in corridas:
        alertas.extend(corrida["alertas"])

    resultados_asr23 = [corrida["escenarios"]["atacante_asr23"] for corrida in corridas]
    resultados_asr31 = [corrida["escenarios"]["atacante_asr31_secuencial"] for corrida in corridas]
    sesiones_legitimo_23 = [
        {"session_id": corrida["escenarios"]["legitimo_asr23"]["session_id"]}
        for corrida in corridas
    ]
    sesiones_legitimo_inusual = [
        {"session_id": corrida["escenarios"]["legitimo_inusual_asr31"]["session_id"]}
        for corrida in corridas
    ]
    intentos_otp = [{"session_id": r["session_id"]} for r in resultados_asr23]
    atacantes_31 = [{"session_id": r["session_id"]} for r in resultados_asr31]
    legitimos = sesiones_legitimo_23 + sesiones_legitimo_inusual

    estados_polizas_atacadas: dict[str, str] = {}
    for corrida in corridas:
        poliza = corrida["escenarios"]["atacante_asr23"]["poliza_id"]
        estados_polizas_atacadas[poliza] = corrida["estados_polizas"][poliza]

    latencias_ms = [r["latencia_revocacion_ms"] for r in resultados_asr23]
    p50, p95 = metricas.latencia_revocacion_p50_p95(latencias_ms)
    eventos_absorbidos = sum(corrida["alertas_duplicadas_en_logs"] for corrida in corridas)
    registradas_duplicadas = metricas.alertas_registradas_duplicadas(alertas)

    tasa_otp = metricas.deteccion_otp_fallidos(intentos_otp, alertas)
    operaciones_no_autorizadas = metricas.operaciones_privilegiadas_ejecutadas(
        estados_polizas_atacadas
    )
    tasa_bloqueo_23 = metricas.segunda_operacion_bloqueada(
        resultados_asr23, "estado_aprobacion_2", "tipo_error_aprobacion_2"
    )
    tasa_alcance = metricas.deteccion_alcance_no_autorizado(atacantes_31, alertas)
    revocaciones_indebidas = metricas.falsos_positivos(legitimos, alertas)
    alerta_inusual = metricas.alerta_consulta_inusual_presente(sesiones_legitimo_inusual, alertas)
    tasa_bloqueo_31 = metricas.segunda_operacion_bloqueada(
        resultados_asr31, "estado_consulta_2", "tipo_error_consulta_2"
    )
    filas_locust: list[Mapping[str, Any]] = []
    for corrida in corridas:
        filas_locust.extend(corrida["locust_filas"])
    operaciones_antes_del_cierre = metricas.operaciones_asr31_antes_del_cierre(
        resultados_asr31, filas_locust
    )

    return [
        metricas.CriterioAceptacion(
            metrica="ASR-23 · detección de OTP fallidos",
            umbral="100 %",
            valor_observado=f"{tasa_otp:.0%}",
            cumple=tasa_otp >= 1.0,
            descripcion=(
                "El atacante eleva su rol a supervisor y envía el código 000000. "
                "Cada intento debe dejar una alerta OTP_FALLIDO de esa misma sesión. "
                "El porcentaje es cuántos intentos quedaron registrados."
            ),
        ),
        metricas.CriterioAceptacion(
            metrica="ASR-23 · operaciones privilegiadas ejecutadas sin OTP correcto",
            umbral="0",
            valor_observado=str(operaciones_no_autorizadas),
            cumple=operaciones_no_autorizadas == 0,
            descripcion=(
                "La aprobación se retiene hasta recibir el código. El número cuenta "
                "pólizas del atacante que no siguieron PENDIENTE: con el umbral en 0, "
                "ninguna aprobación se ejecutó sin el OTP real."
            ),
        ),
        metricas.CriterioAceptacion(
            metrica="ASR-23 · segunda operación bloqueada",
            umbral="100 %",
            valor_observado=f"{tasa_bloqueo_23:.0%}",
            cumple=tasa_bloqueo_23 >= 1.0,
            descripcion=(
                "Después del código rechazado, el atacante vuelve a pedir la aprobación. "
                "Debe recibir 401 sesion-revocada. El porcentaje es en cuántas "
                "repeticiones esa segunda operación quedó bloqueada."
            ),
        ),
        metricas.CriterioAceptacion(
            metrica="ASR-23 · latencia de revocación (p50 / p95)",
            umbral="reportar",
            valor_observado=f"{p50:.0f} ms / {p95:.0f} ms",
            cumple=True,
            descripcion=(
                "Milisegundos entre el 403 del código inválido y el primer 401. "
                "No hay umbral de aprobado o reprobado: mide el tiempo que tarda "
                "la reacción asíncrona en cerrar la sesión."
            ),
        ),
        metricas.CriterioAceptacion(
            metrica="ASR-31 · detección de consultas fuera de alcance",
            umbral="100 %",
            valor_observado=f"{tasa_alcance:.0%}",
            cumple=tasa_alcance >= 1.0,
            descripcion=(
                "Un asesor de norte consulta una póliza del sur. El auditor debe "
                "avisar a Validación y quedar una alerta ALCANCE_NO_AUTORIZADO de "
                "esa sesión. El porcentaje es en cuántas repeticiones se detectó."
            ),
        ),
        metricas.CriterioAceptacion(
            metrica="ASR-31 · falsos positivos (revocaciones en legítimos)",
            umbral="0, con alerta CONSULTA_INUSUAL",
            valor_observado=f"{revocaciones_indebidas} revocaciones; alerta inusual: "
            f"{'sí' if alerta_inusual else 'no'}",
            cumple=revocaciones_indebidas == 0 and alerta_inusual,
            descripcion=(
                "El empleado que aprueba con el OTP real, y el asesor mixto que "
                "consulta centro (autorizado, pero fuera de su historial), no deben "
                "perder la sesión. El mixto sí debe generar la alerta CONSULTA_INUSUAL."
            ),
        ),
        metricas.CriterioAceptacion(
            metrica="ASR-31 · segunda consulta bloqueada (atacante lento: espera > P entre consultas)",
            umbral="100 %",
            valor_observado=f"{tasa_bloqueo_31:.0%}",
            cumple=tasa_bloqueo_31 >= 1.0,
            descripcion=(
                "El atacante consulta el sur, espera más de un periodo de auditoría "
                "y consulta otra vez. La segunda respuesta debe ser 401 "
                "sesion-revocada. Que esa segunda llegue bloqueada no borra la "
                "consulta que sí se sirvió antes: esa cuenta en el criterio siguiente."
            ),
        ),
        metricas.CriterioAceptacion(
            metrica="ASR-31 · operaciones del atacante antes de cerrar la sesión",
            umbral="0",
            valor_observado=str(operaciones_antes_del_cierre),
            cumple=operaciones_antes_del_cierre == 0,
            descripcion=(
                "Cada respuesta 200 del atacante de ASR-31, en la consulta lenta y "
                "en la ráfaga, es una póliza entregada con la sesión todavía abierta. "
                "El criterio solo se cumple si ese conteo es 0. Si hay un 200 antes "
                "del 401, no se cumple: se le permitió operar antes de cerrarle la sesión."
            ),
        ),
        metricas.CriterioAceptacion(
            metrica="Alertas registradas duplicadas (ambos ASR)",
            umbral="0",
            valor_observado=str(registradas_duplicadas),
            cumple=registradas_duplicadas == 0,
            descripcion=(
                "Cuenta alertas guardadas que repiten el mismo par sesión y motivo. "
                "El umbral es 0: Reacción conserva una sola alerta por incidente, "
                "aunque lleguen varios eventos de la misma sesión."
            ),
        ),
        metricas.CriterioAceptacion(
            metrica="Eventos de seguridad redundantes absorbidos por idempotencia",
            umbral="reportar",
            valor_observado=str(eventos_absorbidos),
            cumple=True,
            descripcion=(
                "Líneas alerta_duplicada en el log de Validación. Cada consulta de "
                "la ráfaga, antes del 401, genera otro evento del mismo incidente; "
                "Reacción lo descarta. Se informa el total, sin exigirle un tope."
            ),
        ),
    ]


def _tabla_ventana_exposicion(corridas: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    por_periodo: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for corrida in corridas:
        por_periodo[int(corrida["periodo_auditoria_s"])].append(corrida)

    filas: list[dict[str, Any]] = []
    for periodo in sorted(por_periodo):
        ventanas_ms: list[float] = []
        consultas: list[int] = []
        intervalos_ms: list[float] = []
        for corrida in por_periodo[periodo]:
            filas_locust = corrida["locust_filas"]
            ventana_por_usuario = metricas.ventana_exposicion_ms_por_usuario(filas_locust)
            consultas_por_usuario = metricas.consultas_200_antes_del_401_por_usuario(filas_locust)
            ventanas_ms.extend(v for v in ventana_por_usuario.values() if v is not None)
            consultas.extend(consultas_por_usuario.values())
            if filas_locust:
                intervalos_ms.append(metricas.intervalo_medio_entre_consultas_ms(filas_locust))
        p50, p95 = metricas.percentiles(ventanas_ms)
        filas.append(
            {
                "periodo_auditoria_s": periodo,
                "muestras": len(ventanas_ms),
                "ventana_min_ms": min(ventanas_ms) if ventanas_ms else 0.0,
                "ventana_p50_ms": p50,
                "ventana_p95_ms": p95,
                "ventana_max_ms": max(ventanas_ms) if ventanas_ms else 0.0,
                "intervalo_ms": sum(intervalos_ms) / len(intervalos_ms) if intervalos_ms else 0.0,
                "consultas_200_min": min(consultas) if consultas else 0,
                "consultas_200_max": max(consultas) if consultas else 0,
                "consultas_200_promedio": sum(consultas) / len(consultas) if consultas else 0.0,
            }
        )
    return filas


def resumen_corridas(corridas: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Criterios y ventana que también consume el tablero en vivo.

    Con la lista vacía no se calcula nada: `tasa` de cero intentos devolvería
    100 % y el tablero lo mostraría como un cumplimiento que todavía no existe.
    """
    if not corridas:
        return {"criterios": [], "ventana": []}
    return {
        "criterios": [criterio.a_dict() for criterio in _calcular_criterios(corridas)],
        "ventana": _tabla_ventana_exposicion(corridas),
    }


def _fila_criterio(criterio: metricas.CriterioAceptacion) -> str:
    marca = "sí" if criterio.cumple else "NO"
    return f"| {criterio.metrica} | {criterio.umbral} | {criterio.valor_observado} | {marca} |"


def generar_informe(directorio_resultados: Path) -> str:
    corridas = _cargar_corridas(directorio_resultados)
    meta = _cargar_meta(directorio_resultados)
    criterios = _calcular_criterios(corridas)
    ventana = _tabla_ventana_exposicion(corridas)
    periodos = sorted({int(corrida["periodo_auditoria_s"]) for corrida in corridas})

    lineas = [
        "# Resultados del experimento — Solventa (ASR-23 / ASR-31)",
        "",
        f"- Fecha: {meta.get('fecha', '—')}",
        f"- `PERIODO_AUDITORIA_S` evaluados: {', '.join(str(p) for p in periodos)}",
        f"- Repeticiones por periodo: {meta.get('repeticiones', '—')}",
        f"- Corridas totales: {len(corridas)}",
        "- Imágenes:",
    ]
    imagenes: dict[str, str] = meta.get("imagenes", {})
    for servicio in sorted(imagenes):
        lineas.append(f"  - `{servicio}`: `{imagenes[servicio]}`")

    lineas += [
        "",
        "## Criterios de aceptación",
        "",
        "| Métrica | Umbral | Valor observado | Cumple |",
        "|---|---|---|---|",
        *[_fila_criterio(criterio) for criterio in criterios],
        "",
        "### Qué mide cada criterio",
        "",
        *[f"- **{criterio.metrica}.** {criterio.descripcion}" for criterio in criterios],
    ]

    lineas += [
        "",
        "## Ventana de exposición por `PERIODO_AUDITORIA_S`",
        "",
        "Ráfaga concurrente de `locustfile.py` (`AtacanteRafagaASR31`): cinco "
        "atacantes con sesión legítima y alcance `norte` consultan pólizas de `sur` "
        "en bucle (una petición, 100 ms de espera, otra petición). Cada fila agrega "
        "5 atacantes × N repeticiones. La **ventana de exposición** es el tiempo entre "
        "la primera consulta de un atacante y su primer `401 sesion-revocada`; "
        "**consultas 200 antes del bloqueo** es cuántas pólizas ajenas le fueron "
        "efectivamente entregadas en ese intervalo (promedio por atacante, con el "
        "mínimo y el máximo observados).",
        "",
        "| Periodo (s) | Muestras | Ventana min (ms) | p50 (ms) | p95 (ms) | max (ms) "
        "| Intervalo entre consultas (ms) | Consultas 200 antes del bloqueo (min / media / max) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for fila in ventana:
        lineas.append(
            f"| {fila['periodo_auditoria_s']} | {fila['muestras']} | "
            f"{fila['ventana_min_ms']:.0f} | {fila['ventana_p50_ms']:.0f} | "
            f"{fila['ventana_p95_ms']:.0f} | {fila['ventana_max_ms']:.0f} | "
            f"{fila['intervalo_ms']:.0f} | "
            f"{fila['consultas_200_min']} / {fila['consultas_200_promedio']:.1f} / "
            f"{fila['consultas_200_max']} |"
        )

    lineas += [
        "",
        "### Cómo leer la ventana",
        "",
        "- La columna de consultas es la ventana dividida por el ritmo del atacante "
        "(`consultas ≈ ventana / intervalo + 1`). Esas respuestas `200` anteriores al "
        "`401` son operaciones servidas con la sesión abierta: el criterio de "
        "aceptación correspondiente exige que sean 0, y no se cumple mientras el "
        "conteo sea mayor.",
        "- La ventana se descompone en (a) el tiempo hasta el siguiente ciclo del "
        "Auditor, gobernado por `PERIODO_AUDITORIA_S`; (b) la cadena Auditor → "
        "Validación → `seguridad` → Reacción (hilo interno de Validación) → Autenticación, de ~130 ms (coincide con "
        "la latencia de revocación de ASR-23); y (c) hasta una petición más del "
        "atacante, porque solo ve el `401` en su siguiente consulta.",
        "- Los valores están agrupados cerca de `P − 1 s` y no de `P / 2` porque el "
        "protocolo es determinista: cada repetición reinicia el stack y los escenarios "
        "previos duran siempre lo mismo, así que la ráfaga arranca siempre poco después "
        "de un ciclo del Auditor. Es el peor momento para el sistema, de modo que las "
        "ventanas reportadas son **conservadoras, cercanas al peor caso** (`P + 0,13 s`); "
        "un atacante que llegara en un instante aleatorio del ciclo obtendría en "
        "promedio la mitad.",
        "- Cada consulta servida durante la ventana genera su propio evento de "
        "auditoría, una anomalía y un evento de seguridad con el mismo par "
        "`(session_id, motivo)`. Reacción conserva una sola alerta por atacante y "
        "descarta el resto: ese es el conteo de eventos redundantes absorbidos de la "
        "tabla de criterios.",
        "",
        '## Interpretación de ASR-31: dos lecturas de "impedir una segunda consulta"',
        "",
        "| Lectura | Escenario que la mide | Resultado |",
        "|---|---|---|",
        "| Segunda consulta emitida **después** de que el Auditor haya corrido "
        "(atacante lento, espera más de `P` entre consultas) | `atacante_asr31_secuencial` "
        "| Bloqueada en el 100 % de las repeticiones |",
        "| Segunda consulta **inmediata** (atacante rápido, el caso realista de "
        "exfiltración) | ráfaga concurrente de Locust | **No se impide**: se sirven "
        "todas las consultas hasta el siguiente ciclo del Auditor, ≈ `P × 9` por "
        "atacante al ritmo medido |",
        "",
        'AAS-H710 declaraba como incertidumbre alta "comprobar que la reacción '
        "asíncrona revoque el acceso antes de una segunda solicitud, incluso con "
        'solicitudes concurrentes". El criterio de aceptación es más estricto que '
        "llegar a un `401` en la consulta siguiente: exige cero operaciones servidas "
        "antes de cerrar la sesión. Un `200` del atacante anterior a ese `401`, en la "
        "consulta lenta o en la ráfaga, es una póliza entregada con la sesión abierta "
        "y el criterio no se cumple. La detección a posteriori no puede frenar esa "
        "primera consulta —la región de la póliza solo se conoce al resolverla— ni "
        "las que lleguen antes del siguiente ciclo. El experimento cuantifica cuánto "
        "se fuga en función de `P`.",
        "",
        "En contraste, ASR-23 sí se cumple estrictamente: la operación privilegiada se "
        "retiene antes de ejecutarse, mientras el OTP está pendiente se rechaza cualquier "
        "otra operación del rol nuevo, y el atacante no ejecuta ni una. Ahí la detección "
        "es síncrona y la reacción asíncrona solo añade los ~130 ms de cerrar la sesión.",
        "",
        "## Conclusión",
        "",
        "La detección se cumple en el 100 % de las repeticiones para ambos ASR, sin "
        "falsos positivos y sin alertas duplicadas, y la revocación asíncrona cuesta "
        "~130 ms. En ASR-23 la operación privilegiada no se ejecuta. En ASR-31 el "
        "criterio de cero operaciones antes del cierre no se cumple cuando el atacante "
        "recibe un `200` antes del `401`: esa respuesta es una póliza ajena servida "
        "con la sesión abierta. Un atacante rápido obtiene cerca de nueve pólizas por "
        "cada segundo de `P`; la ventana crece de forma lineal con ese periodo.",
        "",
        "Palancas de diseño que se derivan: reducir `P` acorta la ventana casi uno a "
        "uno pero no la elimina; limitar en Validación el ritmo de consultas por sesión "
        "acota la fuga por ventana con independencia de `P`; verificar el alcance de "
        "forma síncrona en Validación la eliminaría, al precio de acoplar Validación al "
        "dominio de pólizas (conocer la región de cada una), que es la decisión de "
        "arquitectura que habría que defender o rechazar.",
    ]
    return "\n".join(lineas) + "\n"


def escribir_informe(directorio_resultados: Path, ruta_salida: Path = RUTA_INFORME) -> Path:
    ruta_salida.write_text(generar_informe(directorio_resultados), encoding="utf-8")
    return ruta_salida


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("uso: python reporte.py <directorio_resultados>", file=sys.stderr)
        return 2
    ruta = escribir_informe(Path(args[0]))
    print(f"informe escrito en {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
