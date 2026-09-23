"""Semilla de 60 pólizas para el experimento de seguridad.

La lista se duplica a propósito respecto a la de otros servicios: la
coherencia entre copias es un contrato verificado por tests, no una librería
compartida.
"""

import logging
from decimal import Decimal

from gestion_polizas.contracts import EstadoPoliza, Poliza
from gestion_polizas.repositorio import Repositorio

log = logging.getLogger(__name__)

PRODUCTO = "vida_hipotecario"

#: Tasa arbitraria pero fija: la prima es determinista y se deriva del número
#: de póliza, no de un generador aleatorio.
_TASA_PRIMA = Decimal("0.0036")
_UNIDAD_SUMA = Decimal("10000000.00")

REGIONES: tuple[tuple[str, str], ...] = (
    ("NOR", "norte"),
    ("SUR", "sur"),
    ("CEN", "centro"),
)


def _suma_asegurada(n: int) -> str:
    return str(Decimal(n) * _UNIDAD_SUMA)


def _prima_mensual(suma: str) -> str:
    return str((Decimal(suma) * _TASA_PRIMA).quantize(Decimal("0.01")))


def _polizas() -> list[Poliza]:
    polizas: list[Poliza] = []
    for prefijo, region in REGIONES:
        for n in range(1, 21):
            suma = _suma_asegurada(n)
            estado = EstadoPoliza.PENDIENTE if n <= 10 else EstadoPoliza.EMITIDA
            polizas.append(
                Poliza(
                    poliza_id=f"POL-{prefijo}-{n:03d}",
                    cliente_id=f"CLI-{prefijo}-{n:03d}",
                    region=region,
                    producto=PRODUCTO,
                    suma_asegurada=suma,
                    prima_mensual=_prima_mensual(suma),
                    estado=estado,
                )
            )
    return polizas


def sembrar(repositorio: Repositorio) -> int:
    """Inserta las 60 pólizas si la base está vacía. Devuelve cuántas insertó."""
    if repositorio.contar_polizas() > 0:
        return 0
    polizas = _polizas()
    repositorio.insertar_polizas(polizas)
    log.info("semilla aplicada", extra={"polizas": len(polizas)})
    return len(polizas)
