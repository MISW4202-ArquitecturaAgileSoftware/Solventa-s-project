"""Genera el informe del experimento en Markdown, a partir de los JSON crudos.

Escribe `docs/RESULTADOS-EXPERIMENTO.md`. Nada de lo que aparece ahí se teclea a
mano: si un umbral se cumple o no lo decide el dato medido, no el redactor.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
RESULTADOS = RAIZ / "scripts" / "experiment" / "resultados"
SALIDA = RAIZ / "docs" / "RESULTADOS-EXPERIMENTO.md"

# Umbrales del plan (§F7).
UMBRAL_DETECCION = 0.99
UMBRAL_RETARDO_MS = 300

#: Qué mecanismo debe delatar cada modo. Sirve para comprobar que la detección
#: ocurrió por la vía prevista y no por casualidad.
VIA = {
    "premium_offset": "divergencia de hash",
    "factor_skip": "divergencia de hash",
    "rounding_drift": "divergencia de hash",
    "rate_table_stale": "regla de validez",
    "out_of_range": "regla de validez",
    "silent_zero": "regla de validez",
    "slow": "réplica no responde",
    "crash": "réplica no responde",
}


def cargar(nombre: str) -> dict[str, Any] | None:
    ruta = RESULTADOS / nombre
    if not ruta.exists():
        return None
    datos: dict[str, Any] = json.loads(ruta.read_text())
    return datos


def marca(cumple: bool) -> str:
    return "**CUMPLE**" if cumple else "**NO CUMPLE**"


def main() -> int:
    base = cargar("A-baseline.json")
    mascara = cargar("C-enmascaramiento.json")
    modos = sorted((p.stem[2:], json.loads(p.read_text())) for p in RESULTADOS.glob("B-*.json"))

    lineas: list[str] = [
        "# Resultados del experimento — detección y enmascaramiento",
        "",
        "Generado por `scripts/experiment/reporte.py` a partir de los JSON de",
        "`scripts/experiment/resultados/`. Ningún número de este documento se",
        "escribe a mano.",
        "",
        f"Fecha de la corrida: {datetime.now(tz=UTC).isoformat(timespec='seconds')}",
        "",
        "---",
        "",
    ]

    # --- ASR-11 --------------------------------------------------------------
    lineas += [
        "## ASR-11 · Detección de un cálculo erróneo de prima",
        "",
        "Umbral: **≥ 99 %** de los cálculos erróneos inyectados, detectados.",
        "",
        "| Modo de fallo | Vía de detección esperada | Cotizaciones | Incidentes | Tasa |",
        "|---|---|---:|---:|---:|",
    ]
    tasas: list[float] = []
    for modo, datos in modos:
        tasa = datos.get("tasa_deteccion", 0.0)
        tasas.append(tasa)
        lineas.append(
            f"| `{modo}` | {VIA.get(modo, '—')} | {datos['alcanzaron_votacion']} "
            f"| {datos.get('incidentes_registrados', 0)} | {tasa * 100:.2f} % |"
        )

    peor = min(tasas) if tasas else 0.0
    total_inc = sum(d.get("incidentes_registrados", 0) for _, d in modos)
    total_req = sum(d["alcanzaron_votacion"] for _, d in modos)
    global_ = total_inc / total_req if total_req else 0.0
    lineas += [
        "",
        f"- Tasa global: **{global_ * 100:.2f} %** ({total_inc}/{total_req}).",
        f"- Peor modo: **{peor * 100:.2f} %**.",
        f"- Veredicto: {marca(peor >= UMBRAL_DETECCION)} "
        f"(umbral {UMBRAL_DETECCION * 100:.0f} % en TODOS los modos).",
        "",
    ]

    # --- ASR-12 --------------------------------------------------------------
    lineas += [
        "## ASR-12 · Enmascaramiento del cálculo erróneo",
        "",
        "Umbrales: retardo añadido **≤ 300 ms** sobre el p95 de la línea base, y",
        "**0 primas erróneas** entregadas.",
        "",
    ]
    if base and mascara:
        p95_base = base["latencia_ms"]["p95"]
        p95_masc = mascara["latencia_ms"]["p95"]
        retardo = p95_masc - p95_base
        lineas += [
            "| Corrida | n | tasa real | p50 | p95 | p99 | máx |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for etiqueta, datos in (("A · línea base", base), ("C · con fallo activo", mascara)):
            lat = datos["latencia_ms"]
            lineas.append(
                f"| {etiqueta} | {datos['enviadas']} "
                f"| {datos['tasa_real_por_minuto']}/min "
                f"| {lat['p50']} ms | {lat['p95']} ms | {lat['p99']} ms | {lat['max']} ms |"
            )
        lineas += [
            "",
            f"- Retardo añadido sobre el p95: **{retardo:+.2f} ms** "
            f"(base {p95_base} ms → con fallo {p95_masc} ms).",
            f"- Veredicto latencia: {marca(retardo <= UMBRAL_RETARDO_MS)} "
            f"(umbral ≤ {UMBRAL_RETARDO_MS} ms).",
            "",
            f"- Primas erróneas entregadas en la corrida C: "
            f"**{mascara['primas_erroneas']}** de {mascara['latencia_ms']['n']} "
            "respuestas verificadas una a una contra el dominio.",
            f"- Veredicto integridad: {marca(mascara['primas_erroneas'] == 0)} (umbral: 0).",
            "",
            f"- Estados devueltos en la corrida C: `{mascara['por_estado_cotizacion']}`.",
            "",
        ]
    else:
        lineas += ["_Faltan corridas A o C._", ""]

    # --- Límite conocido -----------------------------------------------------
    lineas += [
        "---",
        "",
        "## Límite conocido del diseño",
        "",
        "Las tres réplicas ejecutan el **mismo código**. La votación detecta",
        "fallos *no correlacionados*: un error en una réplica, o en dos con",
        "modos distintos. Un error **sistemático** en la fórmula o en el",
        "tarifario produciría tres resultados idénticos y erróneos, y la",
        "votación reportaría consenso sobre el valor equivocado sin registrar",
        "incidente alguno.",
        "",
        "Detectar eso exigiría N-version programming real —tres",
        "implementaciones independientes del cálculo bajo el mismo contrato—,",
        "que se descartó por coste. Las reglas de validez de §2.4 cubren",
        "parcialmente el hueco: atrapan el resultado estructuralmente imposible",
        "aunque las tres réplicas coincidan, pero no un desvío plausible.",
        "",
    ]

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text("\n".join(lineas), encoding="utf-8")
    print(f"informe escrito en {SALIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
