"""Contratos locales: `EventoAuditoria` (§4.3), el cuerpo y la respuesta de
`POST validacion/v1/anomalias` (§3.4) y la entidad `historial`.

La lectura es estricta: un evento sin los campos que el Auditor necesita es un
`ErrorEventoInvalido`, que el ciclo registra y confirma en lugar de reintentar
para siempre.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self


class ErrorEventoInvalido(Exception):
    """El mensaje del stream no cumple el contrato de §4.3."""


class Decision(StrEnum):
    #: Región autorizada pero inusual: se incorpora al historial.
    ALERTAR = "ALERTAR"
    #: Región fuera de alcance: NO se incorpora; la siguiente consulta vuelve
    #: a informarse y Reacción absorbe el duplicado.
    REVOCAR = "REVOCAR"


# --- Tiempo -------------------------------------------------------------------


def ahora_utc() -> datetime:
    """Instante actual con zona horaria explícita; nunca `datetime.now()` a secas."""
    return datetime.now(tz=UTC)


def iso_utc_ms(momento: datetime) -> str:
    return momento.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def desde_iso_utc(valor: str) -> datetime:
    momento = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if momento.tzinfo is None:
        raise ValueError(f"instante sin zona horaria: {valor!r}")
    return momento


# --- Lectura estricta ---------------------------------------------------------


def _texto(dato: Mapping[str, Any], campo: str) -> str:
    valor = dato.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorEventoInvalido(f"{campo} debe ser una cadena no vacía")
    return valor


def _texto_o_nulo(dato: Mapping[str, Any], campo: str) -> str | None:
    if campo not in dato:
        raise ErrorEventoInvalido(f"{campo} es obligatorio (puede ser null)")
    valor = dato[campo]
    if valor is None:
        return None
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorEventoInvalido(f"{campo} debe ser una cadena no vacía o null")
    return valor


def _objeto(dato: Mapping[str, Any], campo: str) -> Mapping[str, Any]:
    valor = dato.get(campo)
    if not isinstance(valor, dict):
        raise ErrorEventoInvalido(f"{campo} debe ser un objeto JSON")
    return valor


# --- Evento de auditoría (§4.3) -----------------------------------------------


@dataclass(frozen=True, slots=True)
class EventoAuditoria:
    """Solo los campos que el Auditor usa para evaluar el acceso."""

    evento_id: str
    correlation_id: str
    emitido_en: datetime
    employee_id: str
    session_id: str
    accion: str
    poliza_id: str | None
    #: `None` si la póliza no existe: el evento se ignora (§4.3).
    region: str | None

    @classmethod
    def desde_dict(cls, dato: Any) -> Self:
        if not isinstance(dato, dict):
            raise ErrorEventoInvalido("el evento debe ser un objeto JSON")
        actor = _objeto(dato, "actor")
        recurso = _objeto(dato, "recurso")
        try:
            emitido_en = desde_iso_utc(_texto(dato, "emitido_en"))
        except ValueError as err:
            raise ErrorEventoInvalido(f"emitido_en inválido: {err}") from err
        return cls(
            evento_id=_texto(dato, "evento_id"),
            correlation_id=_texto(dato, "correlation_id"),
            emitido_en=emitido_en,
            employee_id=_texto(actor, "employee_id"),
            session_id=_texto(actor, "session_id"),
            accion=_texto(dato, "accion"),
            poliza_id=_texto_o_nulo(recurso, "poliza_id"),
            region=_texto_o_nulo(recurso, "region"),
        )


# --- POST validacion/v1/anomalias (§3.4) ---------------------------------------


@dataclass(frozen=True, slots=True)
class CuerpoAnomalia:
    evento_id: str
    correlation_id: str
    employee_id: str
    session_id: str
    accion: str
    region_consultada: str

    @classmethod
    def desde_evento(cls, evento: EventoAuditoria, region: str) -> Self:
        return cls(
            evento_id=evento.evento_id,
            correlation_id=evento.correlation_id,
            employee_id=evento.employee_id,
            session_id=evento.session_id,
            accion=evento.accion,
            region_consultada=region,
        )

    def a_dict(self) -> dict[str, str]:
        return {
            "evento_id": self.evento_id,
            "correlation_id": self.correlation_id,
            "employee_id": self.employee_id,
            "session_id": self.session_id,
            "accion": self.accion,
            "region_consultada": self.region_consultada,
        }


# --- Historial ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Habito:
    """Una fila de `historial`: una región que el empleado consulta habitualmente."""

    employee_id: str
    region: str
    conteo: int
    primera_vez: datetime
    ultima_vez: datetime
