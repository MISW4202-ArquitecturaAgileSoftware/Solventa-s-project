"""Inyección de fallos (PLAN-IMPLEMENTACION.md §2.6).

Todo lo que esta réplica puede hacer mal está aquí y solo aquí. El resto del
worker no sabe que existen los fallos: llama a `calcular` de este módulo y
obtiene un resultado, correcto o no.

Ningún modo duplica la fórmula actuarial. Los que corrompen la tarifa construyen
un `Tarifario` alterado y llaman al mismo `pricing` del dominio; los que
desvían el importe operan sobre el resultado ya calculado. Dos copias de la
fórmula divergirían por mantenimiento y el experimento acabaría midiendo el bug
equivocado.

Los modos se reparten en tres familias según qué mecanismo de detección
ejercitan, y esa separación es deliberada: si todos fuesen detectables por las
reglas de rango, la votación no haría falta.
"""

import time
from dataclasses import replace
from datetime import date
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum

from cotizador.common import tarifario as tarifario_mod
from cotizador.common.contracts import ResultadoCotizacion, SolicitudCotizacion
from cotizador.common.pricing import CENTAVO, calcular_con_tabla, redondear


class ModoFallo(StrEnum):
    NONE = "none"
    PREMIUM_OFFSET = "premium_offset"
    FACTOR_SKIP = "factor_skip"
    RATE_TABLE_STALE = "rate_table_stale"
    ROUNDING_DRIFT = "rounding_drift"
    OUT_OF_RANGE = "out_of_range"
    SILENT_ZERO = "silent_zero"
    SLOW = "slow"
    CRASH = "crash"


class FalloInyectado(Exception):
    """El modo `crash`: la réplica no llega a producir respuesta."""


#: Modos que NO alteran el resultado, solo el comportamiento temporal.
MODOS_TEMPORALES = frozenset({ModoFallo.SLOW, ModoFallo.CRASH})

#: Desvío de `premium_offset`: ±15 % cae dentro de las cotas de ratio, así que
#: ninguna regla estructural puede verlo. Solo lo delata la divergencia de hash.
OFFSET = Decimal("1.15")
FACTOR_DESORBITADO = Decimal("500")
RETARDO_SLOW_S = 0.4


def _con_prima(resultado: ResultadoCotizacion, prima_mensual: Decimal) -> ResultadoCotizacion:
    """Sustituye la prima manteniendo coherente la anual.

    Mantener la coherencia importa: si la anual quedara descuadrada, la regla
    `coherencia_anual` detectaría el fallo por sí sola y `premium_offset`
    dejaría de servir para probar la detección por divergencia.
    """
    return replace(
        resultado,
        prima_mensual=prima_mensual,
        prima_anual=redondear(prima_mensual * 12),
    )


def calcular(
    solicitud: SolicitudCotizacion,
    fecha_calculo: date,
    version: str,
    modo: str,
) -> ResultadoCotizacion:
    """Calcula la prima aplicando el modo de fallo configurado en esta réplica."""
    try:
        fallo = ModoFallo(modo)
    except ValueError as err:
        raise RuntimeError(f"FAULT_MODE desconocido: {modo!r}") from err

    if fallo is ModoFallo.CRASH:
        raise FalloInyectado("fallo inyectado: crash")

    if fallo is ModoFallo.SLOW:
        time.sleep(RETARDO_SLOW_S)

    # --- Fallos que corrompen la tabla antes de calcular ---------------------
    if fallo is ModoFallo.RATE_TABLE_STALE:
        tabla = tarifario_mod.obtener(tarifario_mod.VERSION_ANTERIOR)
    elif fallo is ModoFallo.FACTOR_SKIP:
        vigente = tarifario_mod.obtener(version)
        tabla = replace(
            vigente,
            factores_clase_ocupacional=dict.fromkeys(
                vigente.factores_clase_ocupacional, Decimal("1.00")
            ),
        )
    else:
        tabla = tarifario_mod.obtener(version)

    resultado = calcular_con_tabla(solicitud, fecha_calculo, tabla)

    # --- Fallos que desvían el importe ya calculado --------------------------
    match fallo:
        case ModoFallo.PREMIUM_OFFSET:
            return _con_prima(resultado, redondear(resultado.prima_mensual * OFFSET))
        case ModoFallo.OUT_OF_RANGE:
            return _con_prima(resultado, redondear(resultado.prima_mensual * FACTOR_DESORBITADO))
        case ModoFallo.SILENT_ZERO:
            return _con_prima(resultado, Decimal("0.00"))
        case ModoFallo.ROUNDING_DRIFT:
            # Trunca a pesos enteros en vez de redondear a centavos: un error de
            # centavos, invisible a simple vista y evidente para el hash.
            truncada = resultado.prima_mensual.quantize(Decimal("1"), rounding=ROUND_DOWN).quantize(
                CENTAVO
            )
            return _con_prima(resultado, truncada)
        case _:
            return resultado
