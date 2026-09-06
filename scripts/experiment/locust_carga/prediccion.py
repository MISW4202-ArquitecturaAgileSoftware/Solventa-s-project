"""¿El modo inyectado produce un error observable en esta solicitud?

No importa `cotizador.faults`: el generador no depende del código de un
servicio. La predicción usa el tarifario del oráculo y las reglas de cada modo.
"""

from datetime import date
from typing import Any

from experiment_common import tarifario as tarifario_mod
from experiment_common.contracts import SolicitudCotizacion
from experiment_common.pricing import calcular

#: Desvían el resultado o la réplica en cualquier solicitud válida.
_SIEMPRE_EFECTIVO = frozenset(
    {
        "premium_offset",
        "rounding_drift",
        "out_of_range",
        "silent_zero",
        "slow",
        "crash",
    }
)


def es_fallo_efectivo(solicitud: dict[str, Any], modo: str, fecha_calculo: date) -> bool:
    """True si el modo alteraría el resultado funcional o dejaría a B muda."""
    if modo == "none":
        return False
    if modo in _SIEMPRE_EFECTIVO:
        return True
    if modo == "factor_skip":
        # Clase 1 ya vale 1.00 en el tarifario: anular los factores no cambia nada.
        return int(solicitud["asegurado"]["clase_ocupacional"]) != 1
    if modo == "rate_table_stale":
        parseada = SolicitudCotizacion.desde_dict(solicitud)
        vigente = calcular(parseada, fecha_calculo, tarifario_mod.VERSION_VIGENTE)
        anterior = calcular(parseada, fecha_calculo, tarifario_mod.VERSION_ANTERIOR)
        return vigente != anterior
    raise ValueError(f"FAULT_MODE desconocido: {modo!r}")
