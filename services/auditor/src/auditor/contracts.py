"""Contratos locales: el `EventoAuditoria` que se consume (§4.3) y el cuerpo de
`POST /v1/anomalias` que se envía a Validación (§3.4).

La lectura es estricta y explícita: un evento malformado se detecta aquí, con
el campo señalado, en vez de fallar a medias más adelante en el ciclo.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self


class ErrorContrato(Exception):
    def __init__(self, campo: str, regla: str) -> None:
        super().__init__(f"{campo} {regla}")
        self.campo = campo


_AUSENTE: Any = object()


def _exigir(dato: Mapping[str, Any], campo: str) -> Any:
    valor = dato.get(campo, _AUSENTE)
    if valor is _AUSENTE:
        raise ErrorContrato(campo, "es obligatorio")
    return valor


def _leer_texto(dato: Mapping[str, Any], campo: str) -> str:
    valor = _exigir(dato, campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorContrato(campo, "debe ser una cadena no vacía")
    return valor


def _leer_texto_opcional(dato: Mapping[str, Any], campo: str) -> str | None:
    valor = _exigir(dato, campo)
    if valor is None:
        return None
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorContrato(campo, "debe ser una cadena no vacía o null")
    return valor


def _leer_enum[E: StrEnum](dato: Mapping[str, Any], campo: str, enumeracion: type[E]) -> E:
    crudo = _leer_texto(dato, campo)
    try:
        return enumeracion(crudo)
    except ValueError as err:
        admitidos = ", ".join(miembro.value for miembro in enumeracion)
        raise ErrorContrato(campo, f"debe ser uno de: {admitidos}") from err


def _leer_mapa(dato: Mapping[str, Any], campo: str) -> Mapping[str, Any]:
    valor = _exigir(dato, campo)
    if not isinstance(valor, Mapping):
        raise ErrorContrato(campo, "debe ser un objeto JSON")
    return valor


def ahora_utc() -> datetime:
    """Instante actual con zona horaria explícita; nunca `datetime.now()` a secas."""
    return datetime.now(tz=UTC)


def iso_utc(momento: datetime) -> str:
    return momento.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def desde_iso_utc(valor: str) -> datetime:
    return datetime.fromisoformat(valor.replace("Z", "+00:00"))


class Rol(StrEnum):
    ASESOR = "asesor"
    SUPERVISOR = "supervisor"


class Accion(StrEnum):
    CONSULTA_POLIZA = "CONSULTA_POLIZA"
    APROBACION_POLIZA = "APROBACION_POLIZA"


class Decision(StrEnum):
    REVOCAR = "REVOCAR"
    ALERTAR = "ALERTAR"
    #: Validación nunca la envía: el Auditor la usa internamente cuando el
    #: empleado le resulta desconocido (404) y no hay nada que decidir.
    IGNORAR = "IGNORAR"


@dataclass(frozen=True, slots=True)
class Actor:
    employee_id: str
    session_id: str
    rol: Rol

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(
            employee_id=_leer_texto(dato, "employee_id"),
            session_id=_leer_texto(dato, "session_id"),
            rol=_leer_enum(dato, "rol", Rol),
        )

    def a_dict(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "session_id": self.session_id,
            "rol": self.rol.value,
        }


@dataclass(frozen=True, slots=True)
class Recurso:
    tipo: str
    poliza_id: str
    region: str | None
    cliente_id: str | None

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(
            tipo=_leer_texto(dato, "tipo"),
            poliza_id=_leer_texto(dato, "poliza_id"),
            region=_leer_texto_opcional(dato, "region"),
            cliente_id=_leer_texto_opcional(dato, "cliente_id"),
        )

    def a_dict(self) -> dict[str, Any]:
        return {
            "tipo": self.tipo,
            "poliza_id": self.poliza_id,
            "region": self.region,
            "cliente_id": self.cliente_id,
        }


@dataclass(frozen=True, slots=True)
class EventoAuditoria:
    evento_id: str
    correlation_id: str
    tipo: str
    version: str
    emitido_en: datetime
    actor: Actor
    accion: Accion
    recurso: Recurso
    resultado: str

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(
            evento_id=_leer_texto(dato, "evento_id"),
            correlation_id=_leer_texto(dato, "correlation_id"),
            tipo=_leer_texto(dato, "tipo"),
            version=_leer_texto(dato, "version"),
            emitido_en=desde_iso_utc(_leer_texto(dato, "emitido_en")),
            actor=Actor.desde_dict(_leer_mapa(dato, "actor")),
            accion=_leer_enum(dato, "accion", Accion),
            recurso=Recurso.desde_dict(_leer_mapa(dato, "recurso")),
            resultado=_leer_texto(dato, "resultado"),
        )

    def a_dict(self) -> dict[str, Any]:
        return {
            "evento_id": self.evento_id,
            "correlation_id": self.correlation_id,
            "tipo": self.tipo,
            "version": self.version,
            "emitido_en": iso_utc(self.emitido_en),
            "actor": self.actor.a_dict(),
            "accion": self.accion.value,
            "recurso": self.recurso.a_dict(),
            "resultado": self.resultado,
        }


@dataclass(frozen=True, slots=True)
class CuerpoAnomalia:
    """Lo que el Auditor envía a `POST validacion/v1/anomalias` (§3.4)."""

    evento_id: str
    correlation_id: str
    employee_id: str
    session_id: str
    accion: Accion
    region_consultada: str

    def a_dict(self) -> dict[str, Any]:
        return {
            "evento_id": self.evento_id,
            "correlation_id": self.correlation_id,
            "employee_id": self.employee_id,
            "session_id": self.session_id,
            "accion": self.accion.value,
            "region_consultada": self.region_consultada,
        }


@dataclass(frozen=True, slots=True)
class RespuestaAnomalia:
    evento_id: str
    decision: Decision

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(
            evento_id=_leer_texto(dato, "evento_id"),
            decision=_leer_enum(dato, "decision", Decision),
        )


@dataclass(frozen=True, slots=True)
class HistorialEntrada:
    employee_id: str
    region: str
    conteo: int
    primera_vez: datetime
    ultima_vez: datetime
