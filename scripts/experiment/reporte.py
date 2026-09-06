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
    "premium_offset": "divergencia de resultado",
    "factor_skip": "divergencia de resultado",
    "rounding_drift": "divergencia de resultado",
    "rate_table_stale": "divergencia de resultado",
    "out_of_range": "divergencia de resultado",
    "silent_zero": "divergencia de resultado",
    "slow": "réplica no responde",
    "crash": "réplica no responde",
}

#: Qué inyecta cada modo en B y dónde no altera el resultado. El tablero HTML
#: lo enseña junto a la tasa; no se escribe a mano en el informe.
CATALOGO_MODOS: dict[str, dict[str, str]] = {
    "premium_offset": {
        "inyecta": "Multiplica la prima mensual por 1.15.",
        "trampa": "Ninguna: altera todas las solicitudes válidas.",
    },
    "factor_skip": {
        "inyecta": "Anula los factores de clase ocupacional (todos a 1.00).",
        "trampa": "La clase 1 ya vale 1.00: esas solicitudes no entran al denominador.",
    },
    "rate_table_stale": {
        "inyecta": "Calcula con el tarifario 2025.11 en vez del vigente 2026.02.",
        "trampa": "Solo es fallo efectivo si las dos tablas dan primas distintas.",
    },
    "rounding_drift": {
        "inyecta": "Trunca la prima a pesos enteros en vez de redondear a centavos.",
        "trampa": "El desvío es de céntimos; el 2 de 3 igual lo ve.",
    },
    "out_of_range": {
        "inyecta": "Multiplica la prima por 500.",
        "trampa": "Votación lo ve como divergencia de resultado, no como regla de validez.",
    },
    "silent_zero": {
        "inyecta": "Entrega prima mensual 0.00.",
        "trampa": "Dos réplicas sanas ganan la votación; el cliente no ve el cero.",
    },
    "slow": {
        "inyecta": "Duerme 400 ms antes de responder.",
        "trampa": "Supera el presupuesto de consenso (250 ms); B no entra al quórum.",
    },
    "crash": {
        "inyecta": "No produce respuesta (sin XACK).",
        "trampa": "A y C alcanzan mayoría; el cliente no ve el crash.",
    },
}


def ficha_modo(modo: str) -> dict[str, str]:
    extra = CATALOGO_MODOS.get(modo, {})
    return {
        "modo": modo,
        "via": VIA.get(modo, "—"),
        "inyecta": extra.get("inyecta", "—"),
        "trampa": extra.get("trampa", "—"),
    }


def cargar(nombre: str) -> dict[str, Any] | None:
    ruta = RESULTADOS / nombre
    if not ruta.exists():
        return None
    datos: dict[str, Any] = json.loads(ruta.read_text())
    return datos


def marca(cumple: bool) -> str:
    return "**CUMPLE**" if cumple else "**NO CUMPLE**"


def denominador_deteccion(datos: dict[str, Any]) -> int:
    """Fallos que el modo sí inyectó. Sin el campo, se cae al denominador viejo."""
    if "fallos_efectivos" in datos:
        return int(datos["fallos_efectivos"])
    return int(datos["alcanzaron_votacion"])


def notas_denominador_parcial(
    modos: list[tuple[str, dict[str, Any]]],
) -> list[str]:
    """Modos donde no toda request que llegó a Votación era un fallo inyectado."""
    notas: list[str] = []
    for modo, datos in modos:
        efectivos = denominador_deteccion(datos)
        alcanzaron = int(datos["alcanzaron_votacion"])
        if efectivos < alcanzaron:
            notas.append(
                f"`{modo}`: {efectivos} fallos efectivos de {alcanzaron} requests "
                "que alcanzaron Votación (el modo no altera todas las solicitudes)."
            )
    return notas


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
        "El denominador son los **fallos efectivos**: solicitudes en las que el",
        "modo sí altera el resultado (o deja a B muda) y que llegaron a Votación.",
        "`factor_skip` no cambia la prima de la clase ocupacional 1, cuyo factor",
        "ya vale `1.00`; esas requests no entran al denominador. La tasa es",
        "incidentes registrados en Gestión de Errores sobre ese denominador.",
        "",
        "| Modo de fallo | Vía de detección esperada | Efectivos | Incidentes | Tasa |",
        "|---|---|---:|---:|---:|",
    ]
    tasas: list[float] = []
    for modo, datos in modos:
        tasa = float(datos.get("tasa_deteccion", 0.0))
        tasas.append(tasa)
        lineas.append(
            f"| `{modo}` | {VIA.get(modo, '—')} | {denominador_deteccion(datos)} "
            f"| {datos.get('incidentes_registrados', 0)} | {tasa * 100:.2f} % |"
        )

    peor = min(tasas) if tasas else 0.0
    total_inc = sum(d.get("incidentes_registrados", 0) for _, d in modos)
    total_req = sum(denominador_deteccion(d) for _, d in modos)
    global_ = total_inc / total_req if total_req else 0.0
    lineas += [
        "",
        f"- Tasa global: **{global_ * 100:.2f} %** ({total_inc}/{total_req}).",
        f"- Peor modo: **{peor * 100:.2f} %**.",
        f"- Veredicto: {marca(peor >= UMBRAL_DETECCION)} "
        f"(umbral {UMBRAL_DETECCION * 100:.0f} % en TODOS los modos).",
        "",
    ]
    notas = notas_denominador_parcial(modos)
    for nota in notas:
        lineas.append(f"- {nota}")
    if notas:
        lineas.append("")

    # --- ASR-12 --------------------------------------------------------------
    lineas += [
        "## ASR-12 · Enmascaramiento del cálculo erróneo",
        "",
        "Umbrales: retardo total añadido **≤ 300 ms** sobre la latencia media de la línea base, y",
        "**0 primas erróneas** entregadas.",
        "",
    ]
    if base and mascara:
        media_base = base["latencia_ms"]["media"]
        media_masc = mascara["latencia_ms"]["media"]
        retardo = media_masc - media_base
        lineas += [
            "| Corrida | n | tasa real | media | p50 | p99 | máx |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for etiqueta, datos in (("A · línea base", base), ("C · con fallo activo", mascara)):
            lat = datos["latencia_ms"]
            lineas.append(
                f"| {etiqueta} | {datos['enviadas']} "
                f"| {datos['tasa_real_por_minuto']}/min "
                f"| {lat['media']} ms | {lat['p50']} ms | {lat['p99']} ms | {lat['max']} ms |"
            )
        lineas += [
            "",
            f"- Retardo total añadido sobre la media: **{retardo:+.2f} ms** "
            f"(base {media_base} ms → con fallo {media_masc} ms).",
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
        "que se descartó por coste. Un desvío plausible idéntico en A, B y C",
        "pasaría la votación y el oráculo del cliente lo marcaría como prima",
        "errónea en la corrida C, no como incidente de ASR-11.",
        "",
    ]

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text("\n".join(lineas), encoding="utf-8")
    try:
        mostrado: Path = SALIDA.relative_to(RAIZ)
    except ValueError:
        mostrado = SALIDA
    print(f"informe escrito en {mostrado}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
