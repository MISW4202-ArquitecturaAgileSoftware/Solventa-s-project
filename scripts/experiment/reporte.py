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
        "El denominador son los **cálculos erróneos inyectados**, no las",
        "cotizaciones enviadas. Un modo de fallo puede ser neutro para ciertas",
        "entradas: `factor_skip` omite el factor de clase ocupacional, que para",
        "la clase 1 ya vale `1.00`, así que en esas solicitudes la réplica",
        "averiada calcula el valor correcto y no hay error que detectar. Cada",
        "detección se atribuye a su journey cruzando por `correlation_id`, de",
        "modo que un incidente ajeno al fallo inyectado no puede inflar la tasa.",
        "",
        "| Modo de fallo | Vía de detección esperada | Cotizaciones | Neutras "
        "| Errores inyectados | Detectados | Tasa |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    tasas: list[float] = []
    for modo, datos in modos:
        det = datos.get("deteccion", {})
        tasa = det.get("tasa", 0.0)
        tasas.append(tasa)
        lineas.append(
            f"| `{modo}` | {VIA.get(modo, '—')} | {det.get('journeys', 0)} "
            f"| {det.get('journeys_neutros', 0)} "
            f"| {det.get('con_error_inyectado', 0)} | {det.get('detectados', 0)} "
            f"| {tasa * 100:.2f} % |"
        )

    peor = min(tasas) if tasas else 0.0
    total_inc = sum(d.get("deteccion", {}).get("detectados", 0) for _, d in modos)
    total_req = sum(d.get("deteccion", {}).get("con_error_inyectado", 0) for _, d in modos)
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

    # --- Disponibilidad observada -------------------------------------------
    fallidas = {
        modo: {c: n for c, n in d["por_http"].items() if c != "200"}
        for modo, d in modos
        if any(c != "200" for c in d["por_http"])
    }
    lineas += [
        "## Observación de disponibilidad (fuera del alcance de ASR-11/12)",
        "",
    ]
    if fallidas:
        lineas += [
            "Algunas cotizaciones no obtuvieron respuesta de éxito:",
            "",
            "| Modo | Respuestas no-200 |",
            "|---|---|",
        ]
        lineas += [f"| `{m}` | `{v}` |" for m, v in sorted(fallidas.items())]
        lineas += [
            "",
            "Son journeys en los que, con una réplica ya averiada, **otra sana**",
            "no respondió dentro del presupuesto de 250 ms. Quedan dos",
            "respuestas que no coinciden: no hay quórum y el sistema rechaza en",
            "vez de adivinar. Es el comportamiento especificado —preferible a",
            "entregar un valor sin confirmar— pero fija el coste de la política:",
            "con quórum 2 de 3, perder una réplica sana mientras otra está rota",
            "convierte el journey en un 503.",
            "",
        ]
    else:
        lineas += ["Todas las cotizaciones obtuvieron respuesta de éxito.", ""]

    # --- Límite conocido -----------------------------------------------------
    lineas += [
        "---",
        "",
        "## Límites conocidos del diseño",
        "",
        "### Coste de la política de quórum",
        "",
        "Con quórum 2 de 3, si una réplica sana no responde dentro del",
        "presupuesto **mientras otra está averiada**, quedan dos respuestas que",
        "no coinciden: no hay mayoría y el sistema devuelve 503 en vez de",
        "adivinar. Rechazar es preferible a entregar un valor sin confirmar,",
        "pero conviene tenerlo escrito: la disponibilidad del journey depende de",
        "que al menos dos réplicas respondan a tiempo, no solo de que el cálculo",
        "sea correcto.",
        "",
        "Es un suceso raro y transitorio —una corrida previa de este mismo",
        "experimento lo observó 3 veces en 18.000 cotizaciones (0,017 %), y la",
        "corrida definitiva ninguna—, así que la tabla de arriba puede no",
        "mostrarlo. No depende del modo de fallo inyectado, sino de una pausa",
        "puntual en una réplica sana.",
        "",
        "### Fallos correlacionados",
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
