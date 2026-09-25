"""Contratos locales: cuerpos HTTP que Autenticación recibe y entidades propias.

La lectura es estricta y explícita: cada campo nombra su regla, de modo que un
cuerpo malformado produce un 422 con el campo señalado y no un 500.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from autenticacion.errors import ErrorValidacion


class Rol(StrEnum):
    ASESOR = "asesor"
    SUPERVISOR = "supervisor"


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


def _leer_enum[E: StrEnum](dato: Mapping[str, Any], campo: str, enumeracion: type[E]) -> E:
    crudo = _leer_texto(dato, campo)
    try:
        return enumeracion(crudo)
    except ValueError as err:
        admitidos = ", ".join(miembro.value for miembro in enumeracion)
        raise ErrorValidacion(campo, f"debe ser uno de: {admitidos}") from err


def ahora_utc() -> datetime:
    """Instante actual con zona horaria explícita; nunca `datetime.now()` a secas."""
    return datetime.now(tz=UTC)


def iso_utc(momento: datetime) -> str:
    return momento.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def desde_iso_utc(valor: str) -> datetime:
    return datetime.fromisoformat(valor.replace("Z", "+00:00"))


# --- Cuerpos de entrada ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CuerpoLogin:
    usuario: str
    password: str

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(usuario=_leer_texto(dato, "usuario"), password=_leer_texto(dato, "password"))


@dataclass(frozen=True, slots=True)
class CuerpoToken:
    token: str

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(token=_leer_texto(dato, "token"))


@dataclass(frozen=True, slots=True)
class CuerpoContencion:
    """Lo que Reacción (dentro de Validación) envía al revocar o bloquear."""

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
class CuerpoRol:
    rol: Rol

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(rol=_leer_enum(dato, "rol", Rol))


# --- Entidades propias -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Empleado:
    employee_id: str
    usuario: str
    hash_password: str
    rol: Rol
    bloqueado_en: datetime | None = None
    motivo_bloqueo: str | None = None

    @property
    def bloqueado(self) -> bool:
        return self.bloqueado_en is not None


@dataclass(frozen=True, slots=True)
class Sesion:
    session_id: str
    employee_id: str
    rol: Rol
    emitida_en: datetime
    expira_en: datetime
    revocada_en: datetime | None = None
    motivo_revocacion: str | None = None

    @property
    def revocada(self) -> bool:
        return self.revocada_en is not None


@dataclass(frozen=True, slots=True)
class SesionEmitida:
    session_id: str
    employee_id: str
    rol: Rol
    token: str
    expira_en: datetime

    def a_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "employee_id": self.employee_id,
            "rol": self.rol.value,
            "token": self.token,
            "expira_en": iso_utc(self.expira_en),
        }


class MotivoInvalidez(StrEnum):
    INVALIDA = "INVALIDA"
    EXPIRADA = "EXPIRADA"
    REVOCADA = "REVOCADA"
    BLOQUEADO = "BLOQUEADO"


@dataclass(frozen=True, slots=True)
class Verificacion:
    """Resultado de verificar un token. Nunca es un error HTTP: el gateway
    necesita el motivo para responder el `type` correcto."""

    valida: bool
    motivo: MotivoInvalidez | None = None
    employee_id: str | None = None
    session_id: str | None = None
    rol: Rol | None = None

    def a_dict(self) -> dict[str, Any]:
        cuerpo: dict[str, Any] = {"valida": self.valida}
        if self.motivo is not None:
            cuerpo["motivo"] = self.motivo.value
        if self.employee_id is not None:
            cuerpo["employee_id"] = self.employee_id
        if self.session_id is not None:
            cuerpo["session_id"] = self.session_id
        if self.rol is not None:
            cuerpo["rol"] = self.rol.value
        return cuerpo
