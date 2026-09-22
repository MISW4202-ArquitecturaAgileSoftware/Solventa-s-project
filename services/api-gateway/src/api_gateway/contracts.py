"""Contratos locales: cuerpos propios y la respuesta de verificación de sesión
que Autenticación devuelve (PLAN-IMPLEMENTACION.md §3.3).

La lectura es estricta y explícita: cada campo nombra su regla, de modo que un
cuerpo del cliente malformado produce un `422 validacion` (el propio) y un
cuerpo del servicio interno con forma inesperada produce un `502 upstream` (el
ajeno), nunca un 500.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self

from api_gateway.errors import ErrorUpstream, ErrorValidacion

_AUSENTE: Any = object()


def _exigir(dato: Mapping[str, Any], campo: str) -> Any:
    valor = dato.get(campo, _AUSENTE)
    if valor is _AUSENTE:
        raise ErrorValidacion(campo, "es obligatorio")
    return valor


def _leer_texto(dato: Mapping[str, Any], campo: str) -> str:
    valor = _exigir(dato, campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorValidacion(campo, "debe ser una cadena no vacía")
    return valor


def _leer_texto_upstream(dato: Mapping[str, Any], campo: str) -> str:
    valor = dato.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorUpstream(f"la verificación de sesión no trae '{campo}'", 502)
    return valor


# --- Cuerpos de entrada (del cliente) ----------------------------------------


@dataclass(frozen=True, slots=True)
class CuerpoOtp:
    codigo: str

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(codigo=_leer_texto(dato, "codigo"))


# --- Actor resuelto por la verificación de sesión ----------------------------


@dataclass(frozen=True, slots=True)
class Actor:
    employee_id: str
    session_id: str
    rol: str

    def a_dict(self) -> dict[str, str]:
        return {"employee_id": self.employee_id, "session_id": self.session_id, "rol": self.rol}


# --- Verificación de sesión (respuesta de autenticacion, §3.3) --------------


class MotivoInvalidez(StrEnum):
    INVALIDA = "INVALIDA"
    EXPIRADA = "EXPIRADA"
    REVOCADA = "REVOCADA"
    BLOQUEADO = "BLOQUEADO"


@dataclass(frozen=True, slots=True)
class VerificacionValida:
    employee_id: str
    session_id: str
    rol: str


@dataclass(frozen=True, slots=True)
class VerificacionInvalida:
    motivo: MotivoInvalidez
    employee_id: str | None
    session_id: str | None


def verificacion_desde_dict(dato: Any) -> VerificacionValida | VerificacionInvalida:
    """`dato` es el cuerpo JSON ya parseado de `POST autenticacion/v1/sesiones/verificar`."""
    if not isinstance(dato, dict) or not isinstance(dato.get("valida"), bool):
        raise ErrorUpstream("la verificación de sesión respondió un cuerpo inesperado", 502)

    if dato["valida"]:
        return VerificacionValida(
            employee_id=_leer_texto_upstream(dato, "employee_id"),
            session_id=_leer_texto_upstream(dato, "session_id"),
            rol=_leer_texto_upstream(dato, "rol"),
        )

    motivo_crudo = dato.get("motivo", "")
    try:
        motivo = MotivoInvalidez(motivo_crudo)
    except ValueError as err:
        raise ErrorUpstream(f"motivo de invalidez desconocido: {motivo_crudo!r}", 502) from err

    employee_id = dato.get("employee_id")
    session_id = dato.get("session_id")
    return VerificacionInvalida(
        motivo=motivo,
        employee_id=employee_id if isinstance(employee_id, str) else None,
        session_id=session_id if isinstance(session_id, str) else None,
    )
