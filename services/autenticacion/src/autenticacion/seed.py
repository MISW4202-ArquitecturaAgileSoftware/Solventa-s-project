"""Semilla de empleados (PLAN-IMPLEMENTACION.md §2.2).

La lista se duplica en cada servicio que la necesita, a propósito: la coherencia
entre copias es un contrato verificado por tests, no una librería compartida.
"""

import logging

from autenticacion import contrasenas
from autenticacion.contracts import Empleado, Rol
from autenticacion.repositorio import Repositorio

log = logging.getLogger(__name__)

PASSWORD = "solventa"

EMPLEADOS: tuple[tuple[str, str, Rol], ...] = (
    *((f"E-ASN-{n:02d}", f"asesor.norte.{n:02d}", Rol.ASESOR) for n in range(1, 11)),
    *((f"E-ASM-{n:02d}", f"asesor.mixto.{n:02d}", Rol.ASESOR) for n in range(1, 3)),
    ("E-SUP-01", "supervisor.01", Rol.SUPERVISOR),
)


def sembrar(repositorio: Repositorio) -> int:
    """Inserta los empleados si la base está vacía. Devuelve cuántos insertó."""
    if repositorio.contar_empleados() > 0:
        return 0
    hash_comun = contrasenas.hashear(PASSWORD)
    empleados = [
        Empleado(employee_id=eid, usuario=usuario, hash_password=hash_comun, rol=rol)
        for eid, usuario, rol in EMPLEADOS
    ]
    repositorio.insertar_empleados(empleados)
    log.info("semilla aplicada", extra={"empleados": len(empleados)})
    return len(empleados)
