"""Semilla de permisos y autorizaciones (PLAN-IMPLEMENTACION.md §2.1, §2.2).

Las listas se duplican en cada servicio que las necesita, a propósito: la
coherencia entre copias es un contrato verificado por tests, no una librería
compartida.
"""

import logging

from validacion.contracts import Autorizacion, Operacion, Rol, ahora_utc
from validacion.repositorio import Repositorio

log = logging.getLogger(__name__)

PERMISOS: tuple[tuple[Rol, Operacion], ...] = (
    (Rol.ASESOR, Operacion.COTIZAR),
    (Rol.ASESOR, Operacion.CONSULTAR_POLIZA),
    (Rol.SUPERVISOR, Operacion.COTIZAR),
    (Rol.SUPERVISOR, Operacion.CONSULTAR_POLIZA),
    (Rol.SUPERVISOR, Operacion.APROBAR_POLIZA),
)

AUTORIZACIONES: tuple[tuple[str, Rol, tuple[str, ...]], ...] = (
    *((f"E-ASN-{n:02d}", Rol.ASESOR, ("norte",)) for n in range(1, 11)),
    *((f"E-ASM-{n:02d}", Rol.ASESOR, ("norte", "centro")) for n in range(1, 3)),
    ("E-SUP-01", Rol.SUPERVISOR, ("norte", "sur", "centro")),
)


def sembrar(repositorio: Repositorio) -> int:
    """Inserta permisos y autorizaciones si la base está vacía. Devuelve cuántas
    autorizaciones insertó."""
    if repositorio.contar_autorizaciones() > 0:
        return 0
    repositorio.insertar_permisos(list(PERMISOS))
    ahora = ahora_utc()
    autorizaciones = [
        Autorizacion(
            employee_id=employee_id,
            ultimo_rol_observado=rol,
            alcance_autorizado=list(alcance),
            canal_otp=f"sim://{employee_id}",
            actualizado_en=ahora,
        )
        for employee_id, rol, alcance in AUTORIZACIONES
    ]
    repositorio.insertar_autorizaciones(autorizaciones)
    log.info(
        "semilla aplicada",
        extra={"autorizaciones": len(autorizaciones), "permisos": len(PERMISOS)},
    )
    return len(autorizaciones)
