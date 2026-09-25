"""Semilla del historial de regiones habituales (PLAN-IMPLEMENTACION.md §2.2).

La lista se duplica en cada servicio que la necesita, a propósito: la coherencia
entre copias es un contrato verificado por tests, no una librería compartida.
"""

import logging

from auditor.contracts import HistorialEntrada, ahora_utc
from auditor.repositorio import Repositorio

log = logging.getLogger(__name__)

EMPLEADOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    *((f"E-ASN-{n:02d}", ("norte",)) for n in range(1, 11)),
    *((f"E-ASM-{n:02d}", ("norte",)) for n in range(1, 3)),
    ("E-SUP-01", ("norte", "sur", "centro")),
)


def sembrar(repositorio: Repositorio) -> int:
    """Inserta el historial si la base está vacía. Devuelve cuántas filas insertó."""
    if repositorio.contar_historial() > 0:
        return 0
    momento = ahora_utc()
    entradas = [
        HistorialEntrada(
            employee_id=employee_id,
            region=region,
            conteo=1,
            primera_vez=momento,
            ultima_vez=momento,
        )
        for employee_id, regiones in EMPLEADOS
        for region in regiones
    ]
    repositorio.insertar_historial(entradas)
    log.info("semilla aplicada", extra={"filas": len(entradas)})
    return len(entradas)
