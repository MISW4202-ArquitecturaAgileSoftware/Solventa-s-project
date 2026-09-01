"""Generador de carga del experimento.

Se escribe en Python y no en k6 porque k6 no está instalado en la máquina, y
además Python da algo que k6 no daría: el script importa `experiment_common` y
**recalcula la prima esperada de cada solicitud**, así que puede comprobar una a
una si el sistema entregó el valor correcto. Esa comprobación es exactamente la
métrica de ASR-12 —«0 primas erróneas entregadas»—, y sin ella habría que
confiar en que el enmascaramiento funcionó en vez de verificarlo.

Las entradas varían (edad, suma, plazo, canal, fumador, clase ocupacional) para
no medir siempre el mismo camino del tarifario, pero se generan de forma
determinista a partir del índice: dos corridas con los mismos parámetros envían
exactamente las mismas solicitudes, y por tanto son comparables.
"""

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from experiment_common.contracts import SolicitudCotizacion
from experiment_common.pricing import calcular

CANALES = ["banco_aliado", "retail", "directo"]
SUMAS = ["80000000.00", "150000000.00", "250000000.00", "400000000.00", "900000000.00"]
PLAZOS = [60, 120, 180, 240, 300]
CLASES = [1, 2, 3, 4]
# Edades repartidas por los seis tramos del tarifario.
EDADES = [22, 27, 33, 38, 44, 47, 52, 57, 63, 68, 71, 74]


def solicitud_de(indice: int, hoy: date) -> dict[str, Any]:
    """Solicitud determinista a partir del índice.

    Los pasos son primos entre sí con las longitudes de las listas para que las
    combinaciones no se repitan en ciclos cortos.
    """
    edad = EDADES[indice % len(EDADES)]
    nacimiento = date(hoy.year - edad, 1, 1) + timedelta(days=(indice * 7) % 300)
    return {
        "producto": "vida_hipotecario",
        "moneda": "COP",
        "suma_asegurada": SUMAS[(indice * 3) % len(SUMAS)],
        "plazo_meses": PLAZOS[(indice * 2) % len(PLAZOS)],
        "canal": CANALES[indice % len(CANALES)],
        "asegurado": {
            "fecha_nacimiento": nacimiento.isoformat(),
            "genero": "FMX"[indice % 3],
            "fumador": indice % 4 == 0,
            "clase_ocupacional": CLASES[(indice * 5) % len(CLASES)],
        },
        "consentimiento_open_finance": True,
    }


@dataclass
class Registro:
    indice: int
    estado_http: int
    latencia_ms: float
    estado_cotizacion: str | None = None
    prima_entregada: str | None = None
    prima_esperada: str | None = None
    erronea: bool = False


def _esperada(cuerpo: dict[str, Any], solicitud: dict[str, Any]) -> Decimal:
    """Prima correcta según el dominio, con la MISMA fecha que usó Votación.

    Se toma de `emitido_en` y no del reloj local: si la corrida cruzara la
    medianoche UTC, recalcular con la fecha de hoy daría una edad distinta y
    marcaría como errónea una prima que es correcta.
    """
    fecha = datetime.fromisoformat(cuerpo["emitido_en"].replace("Z", "+00:00")).date()
    return calcular(SolicitudCotizacion.desde_dict(solicitud), fecha).prima_mensual


def _una(indice: int, url: str, socio: str, hoy: date, timeout: float) -> Registro:
    solicitud = solicitud_de(indice, hoy)
    carga = json.dumps(solicitud).encode("utf-8")
    peticion = urllib.request.Request(
        url,
        data=carga,
        headers={"Content-Type": "application/json", "X-Partner-Id": socio},
        method="POST",
    )
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            cuerpo = json.loads(respuesta.read())
            estado_http = respuesta.status
    except urllib.error.HTTPError as err:
        latencia = (time.perf_counter() - inicio) * 1000
        return Registro(indice, err.code, latencia)
    except Exception:
        latencia = (time.perf_counter() - inicio) * 1000
        return Registro(indice, 0, latencia)

    latencia = (time.perf_counter() - inicio) * 1000
    entregada = Decimal(cuerpo["cotizacion"]["prima_mensual"])
    esperada = _esperada(cuerpo, solicitud)
    return Registro(
        indice=indice,
        estado_http=estado_http,
        latencia_ms=latencia,
        estado_cotizacion=cuerpo.get("estado"),
        prima_entregada=str(entregada),
        prima_esperada=str(esperada),
        erronea=entregada != esperada,
    )


def percentil(valores: list[float], q: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    return ordenados[min(int(len(ordenados) * q), len(ordenados) - 1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--etiqueta", required=True)
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--por-minuto", type=float, default=500.0)
    parser.add_argument("--url", default="http://localhost:8000/v1/cotizaciones")
    parser.add_argument("--socio", default="banco-aliado-01")
    parser.add_argument("--hilos", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--salida", type=Path, required=True)
    args = parser.parse_args()

    hoy = datetime.now(tz=UTC).date()
    tasa_por_s = args.por_minuto / 60
    registros: list[Registro] = []

    arranque = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.hilos) as pool:
        futuros = []
        for i in range(args.n):
            # Ritmo constante: cada solicitud sale en su instante teórico, no en
            # cuanto queda un hilo libre. Sin esto la carga sería a ráfagas y el
            # p95 mediría la contención del generador, no la del sistema.
            espera = (arranque + i / tasa_por_s) - time.perf_counter()
            if espera > 0:
                time.sleep(espera)
            futuros.append(pool.submit(_una, i, args.url, args.socio, hoy, args.timeout))
        registros = [f.result() for f in futuros]

    duracion = time.perf_counter() - arranque
    exitosas = [r for r in registros if r.estado_http == 200]
    latencias = [r.latencia_ms for r in exitosas]
    por_http: dict[str, int] = {}
    por_estado: dict[str, int] = {}
    for r in registros:
        por_http[str(r.estado_http)] = por_http.get(str(r.estado_http), 0) + 1
        if r.estado_cotizacion:
            por_estado[r.estado_cotizacion] = por_estado.get(r.estado_cotizacion, 0) + 1

    erroneas = [r for r in exitosas if r.erronea]
    resumen = {
        "etiqueta": args.etiqueta,
        "enviadas": args.n,
        "duracion_s": round(duracion, 1),
        "tasa_real_por_minuto": round(args.n / duracion * 60, 1),
        "por_http": por_http,
        "por_estado_cotizacion": por_estado,
        # Peticiones que llegaron a Votación: denominador de la tasa de
        # detección. Un 429 nunca pasó del gateway y no ejercitó el fallo.
        "alcanzaron_votacion": sum(n for c, n in por_http.items() if c not in {"429", "0"}),
        "latencia_ms": {
            "n": len(latencias),
            "p50": round(percentil(latencias, 0.50), 2),
            "p95": round(percentil(latencias, 0.95), 2),
            "p99": round(percentil(latencias, 0.99), 2),
            "max": round(max(latencias), 2) if latencias else 0,
            "media": round(statistics.mean(latencias), 2) if latencias else 0,
        },
        "primas_erroneas": len(erroneas),
        "muestras_erroneas": [asdict(r) for r in erroneas[:5]],
    }

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(resumen, indent=2, ensure_ascii=False))
    print(json.dumps(resumen["latencia_ms"] | {"erroneas": len(erroneas)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
