"""Verificación del Bearer contra Autenticación y traducción del `motivo` a un
401 concreto (PLAN-IMPLEMENTACION.md §3.2 pasos 2-3, §5.6)."""

import re

from api_gateway.contracts import (
    Actor,
    MotivoInvalidez,
    VerificacionInvalida,
    VerificacionValida,
    verificacion_desde_dict,
)
from api_gateway.errors import (
    ErrorEmpleadoBloqueado,
    ErrorSesionInvalida,
    ErrorSesionRevocada,
    ErrorSolventa,
)
from api_gateway.http import ClienteHttp

_BEARER = re.compile(r"^Bearer (.+)$")

_MOTIVO_A_ERROR: dict[MotivoInvalidez, type[ErrorSolventa]] = {
    MotivoInvalidez.INVALIDA: ErrorSesionInvalida,
    MotivoInvalidez.EXPIRADA: ErrorSesionInvalida,
    MotivoInvalidez.REVOCADA: ErrorSesionRevocada,
    MotivoInvalidez.BLOQUEADO: ErrorEmpleadoBloqueado,
}


def token_desde_cabecera(valor: str | None) -> str:
    if not valor:
        raise ErrorSesionInvalida("falta la cabecera Authorization")
    coincidencia = _BEARER.match(valor)
    if coincidencia is None or not coincidencia.group(1).strip():
        raise ErrorSesionInvalida("la cabecera Authorization debe ser 'Bearer <token>'")
    return coincidencia.group(1)


def _detalle(verificacion: VerificacionInvalida) -> str:
    partes = [f"motivo={verificacion.motivo.value}"]
    if verificacion.session_id is not None:
        partes.append(f"session_id={verificacion.session_id}")
    return "; ".join(partes)


def verificar(
    cliente: ClienteHttp, url_autenticacion: str, token: str, correlation_id: str
) -> Actor:
    respuesta = cliente.post(
        f"{url_autenticacion}/v1/sesiones/verificar", {"token": token}, correlation_id
    )
    verificacion = verificacion_desde_dict(respuesta.cuerpo)
    if isinstance(verificacion, VerificacionValida):
        return Actor(
            employee_id=verificacion.employee_id,
            session_id=verificacion.session_id,
            rol=verificacion.rol,
        )
    raise _MOTIVO_A_ERROR[verificacion.motivo](_detalle(verificacion))
