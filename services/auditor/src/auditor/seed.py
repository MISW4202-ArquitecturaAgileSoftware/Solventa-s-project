"""Semilla del historial (PLAN-IMPLEMENTACION.md §2.2, columna "Historial").

Las listas se duplican en cada servicio que las necesita, a propósito: la
coherencia entre copias es un contrato verificado por tests, no una librería
compartida. Ojo: el historial NO es el alcance autorizado. `E-ASM-*` tiene
`[norte, centro]` autorizado en Validación pero solo `[norte]` de historial:
por eso su primera consulta a `centro` es "inusual" y no "fuera de alcance".
"""

import logging

from auditor.contracts import Habito, ahora_utc
from auditor.repositorio import Repositorio

log = logging.getLogger(__name__)

HISTORIAL: tuple[tuple[str, tuple[str, ...]], ...] = (
    *((f"E-ASN-{n:02d}", ("norte",)) for n in range(1, 11)),
    *((f"E-ASM-{n:02d}", ("norte",)) for n in range(1, 3)),
    ("E-SUP-01", ("norte", "sur", "centro")),
)


def sembrar(repositorio: Repositorio) -> int:
    """Inserta el historial si la base está vacía. Devuelve cuántas filas insertó."""
    if repositorio.contar() > 0:
        return 0
    ahora = ahora_utc()
    habitos = [
        Habito(employee_id=eid, region=region, conteo=0, primera_vez=ahora, ultima_vez=ahora)
        for eid, regiones in HISTORIAL
        for region in regiones
    ]
    repositorio.insertar(habitos)
    log.info("semilla aplicada", extra={"filas": len(habitos), "empleados": len(HISTORIAL)})
    return len(habitos)
