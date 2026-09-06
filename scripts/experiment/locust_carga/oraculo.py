"""Prima correcta según el dominio, independiente de lo que entregue el sistema."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from experiment_common.contracts import SolicitudCotizacion
from experiment_common.pricing import calcular


def prima_esperada(cuerpo: dict[str, Any], solicitud: dict[str, Any]) -> Decimal:
    """Prima correcta según el dominio, con la MISMA fecha que usó Votación.

    Se toma de `emitido_en` y no del reloj local: si la corrida cruzara la
    medianoche UTC, recalcular con la fecha de hoy daría una edad distinta y
    marcaría como errónea una prima que es correcta.
    """
    fecha = datetime.fromisoformat(cuerpo["emitido_en"].replace("Z", "+00:00")).date()
    return calcular(SolicitudCotizacion.desde_dict(solicitud), fecha).prima_mensual


def es_prima_erronea(cuerpo: dict[str, Any], solicitud: dict[str, Any]) -> bool:
    """True si la prima entregada no coincide bit a bit con el oráculo."""
    entregada = Decimal(cuerpo["cotizacion"]["prima_mensual"])
    return entregada != prima_esperada(cuerpo, solicitud)
