"""Semilla de empleados (PLAN-IMPLEMENTACION.md §2.2).

Las listas se duplican en cada servicio que las necesita, a propósito: la
coherencia entre copias es un contrato verificado por tests, no una librería
compartida.
"""

import logging

from autenticacion import claves
from autenticacion.contracts import Empleado, Rol
from autenticacion.repositorio import Repositorio

log = logging.getLogger(__name__)

#: Contraseña de todos los empleados de prueba (§2.2).
PASSWORD = "solventa"

#: (employee_id, usuario, rol) — el orden es el de la tabla de §2.2.
EMPLEADOS: tuple[tuple[str, str, Rol], ...] = (
    *((f"E-ASN-{n:02d}", f"asesor.norte.{n:02d}", Rol.ASESOR) for n in range(1, 11)),
    *((f"E-ASM-{n:02d}", f"asesor.mixto.{n:02d}", Rol.ASESOR) for n in range(1, 3)),
    ("E-SUP-01", "supervisor.01", Rol.SUPERVISOR),
)


def sembrar(repositorio: Repositorio) -> int:
    """Inserta los empleados si la base está vacía. Devuelve cuántos insertó."""
    if repositorio.contar_empleados() > 0:
        return 0
    empleados = [
        # Un hash por empleado: cada uno con su propia sal, aunque la
        # contraseña sea la misma para todos.
        Empleado(
            employee_id=employee_id,
            usuario=usuario,
            hash_password=claves.hashear(PASSWORD),
            rol=rol,
        )
        for employee_id, usuario, rol in EMPLEADOS
    ]
    repositorio.insertar_empleados(empleados)
    log.info("semilla aplicada", extra={"empleados": len(empleados)})
    return len(empleados)
