"""Contratos locales: cuerpos HTTP de §3.3 y entidades propias.

La lectura es estricta y explícita: cada campo nombra su regla, de modo que un
cuerpo malformado produce un 422 con el campo señalado y no un 500.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from autenticacion.errors import ErrorValidacion


class Rol(StrEnum):
    ASESOR = "asesor"
    SUPERVISOR = "supervisor"


class MotivoInvalidez(StrEnum):
    """Por qué `POST /v1/sesiones/verificar` no valida un token (§5.6). El
    gateway traduce cada uno a un `type` 401 distinto."""

    INVALIDA = "INVALIDA"
    EXPIRADA = "EXPIRADA"
    REVOCADA = "REVOCADA"
    BLOQUEADO = "BLOQUEADO"


# --- Tiempo -------------------------------------------------------------------


def ahora_utc() -> datetime:
    """Instante actual con zona horaria explícita; nunca `datetime.now()` a secas."""
    return datetime.now(tz=UTC)


def iso_utc(momento: datetime) -> str:
    return momento.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def desde_iso_utc(valor: str) -> datetime:
    return datetime.fromisoformat(valor.replace("Z", "+00:00"))


def desde_epoch(segundos: int) -> datetime:
    return datetime.fromtimestamp(segundos, tz=UTC)


# --- Lectura estricta ---------------------------------------------------------

_AUSENTE: Any = object()


def _exigir(dato: Mapping[str, Any], campo: str) -> Any:
    valor = dato.get(campo, _AUSENTE)
    if valor is _AUSENTE:
        raise ErrorValidacion(f"{campo} es obligatorio")
    return valor


def _leer_texto(dato: Mapping[str, Any], campo: str) -> str:
    valor = _exigir(dato, campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorValidacion(f"{campo} debe ser una cadena no vacía")
    return valor


def _leer_rol(dato: Mapping[str, Any], campo: str) -> Rol:
    crudo = _leer_texto(dato, campo)
    try:
        return Rol(crudo)
    except ValueError as err:
        admitidos = ", ".join(rol.value for rol in Rol)
        raise ErrorValidacion(f"{campo} debe ser uno de: {admitidos}") from err


# --- Cuerpos de entrada -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CuerpoLogin:
    usuario: str
    #: Fuera del `repr`: nunca debe acabar en un log ni en una traza.
    password: str = field(repr=False)

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(usuario=_leer_texto(dato, "usuario"), password=_leer_texto(dato, "password"))


@dataclass(frozen=True, slots=True)
class CuerpoVerificacion:
    token: str

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(token=_leer_texto(dato, "token"))


@dataclass(frozen=True, slots=True)
class CuerpoContencion:
    """Cuerpo de revocación y de bloqueo: ambos los envía Reacción con el
    evento de seguridad que los origina, para que el rastro quede completo."""

    motivo: str
    correlation_id: str
    evento_id: str

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(
            motivo=_leer_texto(dato, "motivo"),
            correlation_id=_leer_texto(dato, "correlation_id"),
            evento_id=_leer_texto(dato, "evento_id"),
        )


@dataclass(frozen=True, slots=True)
class CuerpoCambioRol:
    rol: Rol

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(rol=_leer_rol(dato, "rol"))


# --- Entidades ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Empleado:
    employee_id: str
    usuario: str
    hash_password: str
    rol: Rol
    bloqueado_en: datetime | None = None
    motivo_bloqueo: str | None = None


@dataclass(frozen=True, slots=True)
class Sesion:
    session_id: str
    employee_id: str
    #: Rol del empleado en el momento del login; es el que lleva el token.
    rol: Rol
    emitida_en: datetime
    expira_en: datetime
    revocada_en: datetime | None = None
    motivo_revocacion: str | None = None
    correlation_id_revocacion: str | None = None
