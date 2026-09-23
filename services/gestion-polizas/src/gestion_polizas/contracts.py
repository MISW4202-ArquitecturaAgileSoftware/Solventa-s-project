"""Contratos de operación, respuesta y auditoría, y entidades de pólizas.

La lectura del sobre entrante es estricta y explícita: cada campo nombra su
regla, de modo que un parámetro inválido produce `codigo VALIDACION` y no una
excepción sin contexto.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self


class ErrorValidacionSobre(Exception):
    """Un campo del sobre o de sus parámetros no cumple su regla."""

    def __init__(self, campo: str, regla: str) -> None:
        super().__init__(f"{campo} {regla}")
        self.campo = campo


_AUSENTE: Any = object()


def _exigir(dato: Mapping[str, Any], campo: str) -> Any:
    valor = dato.get(campo, _AUSENTE)
    if valor is _AUSENTE:
        raise ErrorValidacionSobre(campo, "es obligatorio")
    return valor


def _leer_texto(dato: Mapping[str, Any], campo: str) -> str:
    valor = _exigir(dato, campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorValidacionSobre(campo, "debe ser una cadena no vacía")
    return valor


def _leer_mapa(dato: Mapping[str, Any], campo: str) -> Mapping[str, Any]:
    valor = _exigir(dato, campo)
    if not isinstance(valor, Mapping):
        raise ErrorValidacionSobre(campo, "debe ser un objeto")
    return valor


def ahora_utc() -> datetime:
    """Instante actual con zona horaria explícita; nunca `datetime.now()` a secas."""
    return datetime.now(tz=UTC)


def iso_utc(momento: datetime) -> str:
    return momento.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def iso_utc_ms(momento: datetime) -> str:
    return momento.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def desde_iso_utc(valor: str) -> datetime:
    return datetime.fromisoformat(valor.replace("Z", "+00:00"))


# --- Envelope entrante --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Actor:
    """Identidad recibida de Validación, que autoriza la operación.

    El worker no verifica rol ni alcance; Redis debe restringir sus productores.
    """

    employee_id: str
    session_id: str
    rol: str

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(
            employee_id=_leer_texto(dato, "employee_id"),
            session_id=_leer_texto(dato, "session_id"),
            rol=_leer_texto(dato, "rol"),
        )

    def a_dict(self) -> dict[str, Any]:
        return {"employee_id": self.employee_id, "session_id": self.session_id, "rol": self.rol}


@dataclass(frozen=True, slots=True)
class SobreOperacion:
    correlation_id: str
    tipo: str
    version: str
    emitido_en: str
    actor: Actor
    operacion: str
    parametros: Mapping[str, Any]

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(
            correlation_id=_leer_texto(dato, "correlation_id"),
            tipo=_leer_texto(dato, "tipo"),
            version=_leer_texto(dato, "version"),
            emitido_en=_leer_texto(dato, "emitido_en"),
            actor=Actor.desde_dict(_leer_mapa(dato, "actor")),
            operacion=_leer_texto(dato, "operacion"),
            parametros=_leer_mapa(dato, "parametros"),
        )


@dataclass(frozen=True, slots=True)
class ParametrosPoliza:
    """Parámetros comunes a `consultar_poliza` y `aprobar_poliza`."""

    poliza_id: str

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(poliza_id=_leer_texto(dato, "poliza_id"))


# --- Respuesta saliente --------------------------------------------------------


class EstadoRespuesta(StrEnum):
    OK = "OK"
    ERROR = "ERROR"


class CodigoRespuesta(StrEnum):
    OK = "OK"
    NO_ENCONTRADA = "NO_ENCONTRADA"
    ESTADO_INVALIDO = "ESTADO_INVALIDO"
    VALIDACION = "VALIDACION"
    INTERNO = "INTERNO"


@dataclass(frozen=True, slots=True)
class SobreRespuesta:
    correlation_id: str
    estado: EstadoRespuesta
    codigo: CodigoRespuesta
    duracion_ms: int
    resultado: Mapping[str, Any] | None = None
    error: str | None = None
    tipo: str = "operacion.resuelta"
    servicio: str = "gestion-polizas"

    def a_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "tipo": self.tipo,
            "servicio": self.servicio,
            "estado": self.estado.value,
            "codigo": self.codigo.value,
            "duracion_ms": self.duracion_ms,
            "resultado": self.resultado,
            "error": self.error,
        }


# --- Evento de auditoría --------------------------------------------------------


class AccionAuditoria(StrEnum):
    CONSULTA_POLIZA = "CONSULTA_POLIZA"
    APROBACION_POLIZA = "APROBACION_POLIZA"


@dataclass(frozen=True, slots=True)
class RecursoPoliza:
    #: `None` cuando el sobre no traía un `poliza_id` legible (parámetros
    #: inválidos); `region` y `cliente_id` van en `None` además cuando la
    #: póliza referenciada no existe.
    poliza_id: str | None
    region: str | None
    cliente_id: str | None
    tipo: str = "poliza"

    def a_dict(self) -> dict[str, Any]:
        return {
            "tipo": self.tipo,
            "poliza_id": self.poliza_id,
            "region": self.region,
            "cliente_id": self.cliente_id,
        }


@dataclass(frozen=True, slots=True)
class EventoAuditoria:
    """Nunca lleva el contenido de la póliza: solo lo necesario para evaluar
    el acceso."""

    evento_id: str
    correlation_id: str
    emitido_en: datetime
    actor: Actor
    accion: AccionAuditoria
    recurso: RecursoPoliza
    resultado: str
    tipo: str = "operacion.auditada"
    version: str = "1"

    def a_dict(self) -> dict[str, Any]:
        return {
            "evento_id": self.evento_id,
            "correlation_id": self.correlation_id,
            "tipo": self.tipo,
            "version": self.version,
            "emitido_en": iso_utc_ms(self.emitido_en),
            "actor": self.actor.a_dict(),
            "accion": self.accion.value,
            "recurso": self.recurso.a_dict(),
            "resultado": self.resultado,
        }


# --- Entidad propia: póliza --------------------------------------------------


class EstadoPoliza(StrEnum):
    PENDIENTE = "PENDIENTE"
    EMITIDA = "EMITIDA"
    APROBADA = "APROBADA"


@dataclass(frozen=True, slots=True)
class Poliza:
    poliza_id: str
    cliente_id: str
    region: str
    producto: str
    #: Cadena decimal, nunca float: el dinero no redondea silenciosamente.
    suma_asegurada: str
    prima_mensual: str
    estado: EstadoPoliza
    aprobada_por: str | None = None
    aprobada_en: datetime | None = None

    def a_dict(self) -> dict[str, Any]:
        return {
            "poliza_id": self.poliza_id,
            "cliente_id": self.cliente_id,
            "region": self.region,
            "producto": self.producto,
            "suma_asegurada": self.suma_asegurada,
            "prima_mensual": self.prima_mensual,
            "estado": self.estado.value,
            "aprobada_por": self.aprobada_por,
            "aprobada_en": iso_utc(self.aprobada_en) if self.aprobada_en is not None else None,
        }
