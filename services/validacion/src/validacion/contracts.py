"""Contratos locales: cuerpos HTTP, sobres de Redis y entidades propias.

La lectura es estricta y explícita: cada campo nombra su regla, de modo que un
cuerpo malformado produce un 422 con el campo señalado y no un 500.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from validacion.errors import ErrorValidacion


class Rol(StrEnum):
    ASESOR = "asesor"
    SUPERVISOR = "supervisor"


class Operacion(StrEnum):
    COTIZAR = "cotizar"
    CONSULTAR_POLIZA = "consultar_poliza"
    APROBAR_POLIZA = "aprobar_poliza"


class EstadoRespuesta(StrEnum):
    OK = "OK"
    ERROR = "ERROR"


class CodigoRespuesta(StrEnum):
    OK = "OK"
    NO_ENCONTRADA = "NO_ENCONTRADA"
    ESTADO_INVALIDO = "ESTADO_INVALIDO"
    VALIDACION = "VALIDACION"
    INTERNO = "INTERNO"


class MotivoSeguridad(StrEnum):
    OTP_FALLIDO = "OTP_FALLIDO"
    ALCANCE_NO_AUTORIZADO = "ALCANCE_NO_AUTORIZADO"
    CONSULTA_INUSUAL = "CONSULTA_INUSUAL"


class AccionSeguridad(StrEnum):
    REVOCAR = "REVOCAR"
    ALERTAR = "ALERTAR"


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


def _leer_objeto(dato: Mapping[str, Any], campo: str) -> Mapping[str, Any]:
    valor = _exigir(dato, campo)
    if not isinstance(valor, dict):
        raise ErrorValidacion(f"{campo} debe ser un objeto JSON")
    return valor


def _leer_enum[E: StrEnum](dato: Mapping[str, Any], campo: str, enumeracion: type[E]) -> E:
    crudo = _leer_texto(dato, campo)
    try:
        return enumeracion(crudo)
    except ValueError as err:
        admitidos = ", ".join(miembro.value for miembro in enumeracion)
        raise ErrorValidacion(f"{campo} debe ser uno de: {admitidos}") from err


def ahora_utc() -> datetime:
    """Instante actual con zona horaria explícita; nunca `datetime.now()` a secas."""
    return datetime.now(tz=UTC)


def iso_utc(momento: datetime) -> str:
    return momento.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def iso_utc_ms(momento: datetime) -> str:
    """Precisión de milisegundos: la usan los sobres y eventos de §4, no las
    respuestas HTTP de negocio (esas van en segundos, como en Autenticación)."""
    return momento.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def desde_iso_utc(valor: str) -> datetime:
    return datetime.fromisoformat(valor.replace("Z", "+00:00"))


def fecha_utc(momento: datetime) -> str:
    return momento.astimezone(UTC).date().isoformat()


# --- Actor --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Actor:
    employee_id: str
    session_id: str
    rol: Rol

    def a_dict(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "session_id": self.session_id,
            "rol": self.rol.value,
        }

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(
            employee_id=_leer_texto(dato, "employee_id"),
            session_id=_leer_texto(dato, "session_id"),
            rol=_leer_enum(dato, "rol", Rol),
        )


# --- Cuerpos de entrada ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CuerpoOperacion:
    correlation_id: str
    actor: Actor
    operacion: Operacion
    parametros: dict[str, Any]

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(
            correlation_id=_leer_texto(dato, "correlation_id"),
            actor=Actor.desde_dict(_leer_objeto(dato, "actor")),
            operacion=_leer_enum(dato, "operacion", Operacion),
            parametros=dict(_leer_objeto(dato, "parametros")),
        )


@dataclass(frozen=True, slots=True)
class CuerpoOtp:
    correlation_id: str
    session_id: str
    codigo: str

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(
            correlation_id=_leer_texto(dato, "correlation_id"),
            session_id=_leer_texto(dato, "session_id"),
            codigo=_leer_texto(dato, "codigo"),
        )


@dataclass(frozen=True, slots=True)
class CuerpoAnomalia:
    evento_id: str
    correlation_id: str
    employee_id: str
    session_id: str
    accion: str
    region_consultada: str

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(
            evento_id=_leer_texto(dato, "evento_id"),
            correlation_id=_leer_texto(dato, "correlation_id"),
            employee_id=_leer_texto(dato, "employee_id"),
            session_id=_leer_texto(dato, "session_id"),
            accion=_leer_texto(dato, "accion"),
            region_consultada=_leer_texto(dato, "region_consultada"),
        )


# --- Sobres de Redis (§4) -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SobreOperacion:
    """`XADD sol:polizas` / `XADD sol:cotizador` — PLAN-IMPLEMENTACION.md §4.1."""

    correlation_id: str
    emitido_en: datetime
    actor: Actor
    operacion: Operacion
    parametros: dict[str, Any]
    #: Solo para `cotizar`: el worker no consulta su reloj.
    fecha_calculo: str | None = None

    def a_dict(self) -> dict[str, Any]:
        cuerpo: dict[str, Any] = {
            "correlation_id": self.correlation_id,
            "tipo": "operacion.solicitada",
            "version": "1",
            "emitido_en": iso_utc_ms(self.emitido_en),
            "actor": self.actor.a_dict(),
            "operacion": self.operacion.value,
            "parametros": self.parametros,
        }
        if self.fecha_calculo is not None:
            cuerpo["fecha_calculo"] = self.fecha_calculo
        return cuerpo

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        fecha_calculo = dato.get("fecha_calculo")
        return cls(
            correlation_id=_leer_texto(dato, "correlation_id"),
            emitido_en=desde_iso_utc(_leer_texto(dato, "emitido_en")),
            actor=Actor.desde_dict(_leer_objeto(dato, "actor")),
            operacion=_leer_enum(dato, "operacion", Operacion),
            parametros=dict(_leer_objeto(dato, "parametros")),
            fecha_calculo=fecha_calculo if isinstance(fecha_calculo, str) else None,
        )

    @classmethod
    def desde_operacion(cls, cuerpo: CuerpoOperacion, emitido_en: datetime) -> Self:
        fecha_calculo = fecha_utc(emitido_en) if cuerpo.operacion is Operacion.COTIZAR else None
        return cls(
            correlation_id=cuerpo.correlation_id,
            emitido_en=emitido_en,
            actor=cuerpo.actor,
            operacion=cuerpo.operacion,
            parametros=cuerpo.parametros,
            fecha_calculo=fecha_calculo,
        )


@dataclass(frozen=True, slots=True)
class SobreRespuesta:
    """`LPUSH resp:{correlation_id}` — PLAN-IMPLEMENTACION.md §4.2."""

    correlation_id: str
    servicio: str
    estado: EstadoRespuesta
    codigo: CodigoRespuesta
    duracion_ms: int
    resultado: dict[str, Any] | None
    error: str | None

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        resultado = dato.get("resultado")
        error = dato.get("error")
        return cls(
            correlation_id=_leer_texto(dato, "correlation_id"),
            servicio=_leer_texto(dato, "servicio"),
            estado=_leer_enum(dato, "estado", EstadoRespuesta),
            codigo=_leer_enum(dato, "codigo", CodigoRespuesta),
            duracion_ms=int(dato.get("duracion_ms") or 0),
            resultado=resultado if isinstance(resultado, dict) else None,
            error=error if isinstance(error, str) else None,
        )


@dataclass(frozen=True, slots=True)
class EventoSeguridad:
    """`XADD seguridad` — PLAN-IMPLEMENTACION.md §4.4."""

    evento_id: str
    correlation_id: str
    emitido_en: datetime
    employee_id: str
    session_id: str
    motivo: MotivoSeguridad
    accion: AccionSeguridad
    detalle: dict[str, Any]

    def a_dict(self) -> dict[str, Any]:
        return {
            "evento_id": self.evento_id,
            "correlation_id": self.correlation_id,
            "tipo": "incidente.detectado",
            "version": "1",
            "emitido_en": iso_utc_ms(self.emitido_en),
            "employee_id": self.employee_id,
            "session_id": self.session_id,
            "motivo": self.motivo.value,
            "accion": self.accion.value,
            "detalle": self.detalle,
        }

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        """Lectura estricta para el consumidor de Reacción: un mensaje corrupto
        en la cola produce `ErrorValidacion` y se registra, no tumba el hilo."""
        return cls(
            evento_id=_leer_texto(dato, "evento_id"),
            correlation_id=_leer_texto(dato, "correlation_id"),
            emitido_en=desde_iso_utc(_leer_texto(dato, "emitido_en")),
            employee_id=_leer_texto(dato, "employee_id"),
            session_id=_leer_texto(dato, "session_id"),
            motivo=_leer_enum(dato, "motivo", MotivoSeguridad),
            accion=_leer_enum(dato, "accion", AccionSeguridad),
            detalle=dict(_leer_objeto(dato, "detalle")),
        )


@dataclass(frozen=True, slots=True)
class Alerta:
    """Fila de la tabla `alertas` (§5.5): `UNIQUE(session_id, motivo)`."""

    evento_id: str
    session_id: str
    employee_id: str
    motivo: MotivoSeguridad
    accion: AccionSeguridad
    correlation_id: str
    detalle: dict[str, Any]
    recibida_en: datetime
    revocada_en: datetime | None = None
    bloqueado_en: datetime | None = None

    def a_dict(self) -> dict[str, Any]:
        return {
            "evento_id": self.evento_id,
            "session_id": self.session_id,
            "employee_id": self.employee_id,
            "motivo": self.motivo.value,
            "accion": self.accion.value,
            "correlation_id": self.correlation_id,
            "detalle": self.detalle,
            "recibida_en": iso_utc_ms(self.recibida_en),
            "revocada_en": iso_utc_ms(self.revocada_en) if self.revocada_en is not None else None,
            "bloqueado_en": (
                iso_utc_ms(self.bloqueado_en) if self.bloqueado_en is not None else None
            ),
        }


# --- Entidades propias ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Autorizacion:
    employee_id: str
    ultimo_rol_observado: Rol
    alcance_autorizado: list[str]
    canal_otp: str
    actualizado_en: datetime


@dataclass(frozen=True, slots=True)
class OtpPendiente:
    session_id: str
    codigo: str
    correlation_id: str
    sobre: SobreOperacion
    creado_en: datetime
