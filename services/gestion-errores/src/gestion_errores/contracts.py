"""Contrato mínimo del incidente que Votación registra como evidencia."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from gestion_errores.errors import ErrorValidacion


class TipoIncidente(StrEnum):
    DIVERGENCIA_RESULTADO = "divergencia_resultado"
    SIN_QUORUM = "sin_quorum"
    REPLICA_NO_RESPONDE = "replica_no_responde"


def _texto(dato: Mapping[str, Any], campo: str) -> str:
    valor = dato.get(campo)
    if not isinstance(valor, str) or not valor:
        raise ErrorValidacion(campo, "debe ser una cadena no vacía")
    return valor


def _instante(dato: Mapping[str, Any], campo: str) -> datetime:
    crudo = _texto(dato, campo)
    try:
        instante = datetime.fromisoformat(crudo.replace("Z", "+00:00"))
    except ValueError as err:
        raise ErrorValidacion(campo, "debe ser un instante ISO-8601") from err
    if instante.tzinfo is None:
        raise ErrorValidacion(campo, "debe incluir zona horaria")
    return instante


def _iso_utc(instante: datetime) -> str:
    return instante.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ValorRecibido:
    cotizador_id: str
    resultado: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        crudo_resultado = dato.get("resultado")
        if crudo_resultado is not None and not isinstance(crudo_resultado, Mapping):
            raise ErrorValidacion("valores_recibidos.resultado", "debe ser un objeto o null")
        crudo_error = dato.get("error")
        if crudo_error is not None and not isinstance(crudo_error, str):
            raise ErrorValidacion("valores_recibidos.error", "debe ser una cadena o null")
        return cls(
            cotizador_id=_texto(dato, "cotizador_id"),
            resultado=dict(crudo_resultado) if crudo_resultado is not None else None,
            error=crudo_error,
        )

    def a_dict(self) -> dict[str, Any]:
        return {
            "cotizador_id": self.cotizador_id,
            "resultado": self.resultado,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class Incidente:
    correlation_id: str
    tipo: TipoIncidente
    detectado_en: datetime
    replicas_divergentes: tuple[str, ...] = ()
    valores_recibidos: tuple[ValorRecibido, ...] = ()
    detalle: str | None = None

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        crudo_tipo = _texto(dato, "tipo")
        try:
            tipo = TipoIncidente(crudo_tipo)
        except ValueError as err:
            admitidos = ", ".join(tipo.value for tipo in TipoIncidente)
            raise ErrorValidacion("tipo", f"debe ser uno de: {admitidos}") from err

        crudo_divergentes = dato.get("replicas_divergentes", [])
        if not isinstance(crudo_divergentes, list) or not all(
            isinstance(replica, str) for replica in crudo_divergentes
        ):
            raise ErrorValidacion("replicas_divergentes", "debe ser una lista de cadenas")

        crudo_valores = dato.get("valores_recibidos", [])
        if not isinstance(crudo_valores, list) or not all(
            isinstance(valor, Mapping) for valor in crudo_valores
        ):
            raise ErrorValidacion("valores_recibidos", "debe ser una lista de objetos")

        crudo_detalle = dato.get("detalle")
        if crudo_detalle is not None and not isinstance(crudo_detalle, str):
            raise ErrorValidacion("detalle", "debe ser una cadena o null")

        return cls(
            correlation_id=_texto(dato, "correlation_id"),
            tipo=tipo,
            detectado_en=_instante(dato, "detectado_en"),
            replicas_divergentes=tuple(crudo_divergentes),
            valores_recibidos=tuple(ValorRecibido.desde_dict(valor) for valor in crudo_valores),
            detalle=crudo_detalle,
        )

    def a_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "tipo": self.tipo.value,
            "detectado_en": _iso_utc(self.detectado_en),
            "replicas_divergentes": list(self.replicas_divergentes),
            "valores_recibidos": [valor.a_dict() for valor in self.valores_recibidos],
            "detalle": self.detalle,
        }
