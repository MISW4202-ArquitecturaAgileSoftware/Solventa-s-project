"""Contratos locales: payloads públicos y envelope interno.

Todas las estructuras son inmutables (`frozen=True`). El Cotizador implementa
solo las direcciones que utiliza: recibe solicitudes y publica respuestas.

Regla dura sobre el dinero: los importes viajan como **cadena decimal**, nunca
como número JSON. Un `float` no representa exactamente valores monetarios, y una
diferencia en el último bit entre dos réplicas produciría una divergencia falsa
en la votación, que es justo lo que el experimento mide.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Self

from cotizador.errors import ErrorValidacion

# --- Enumeraciones del contrato ---------------------------------------------


class Producto(StrEnum):
    VIDA_HIPOTECARIO = "vida_hipotecario"


class Moneda(StrEnum):
    COP = "COP"


class Canal(StrEnum):
    BANCO_ALIADO = "banco_aliado"
    RETAIL = "retail"
    DIRECTO = "directo"


class Genero(StrEnum):
    """No afecta la tarifa; se registra por trazabilidad de la decisión."""

    F = "F"
    M = "M"
    X = "X"


class EstadoRespuesta(StrEnum):
    OK = "OK"
    ERROR = "ERROR"


# --- Límites del contrato de entrada (PLAN-IMPLEMENTACION.md §1.2) ----------

SUMA_ASEGURADA_MIN = Decimal("10000000")
SUMA_ASEGURADA_MAX = Decimal("2000000000")
PLAZO_MESES_MIN = 12
PLAZO_MESES_MAX = 360
CLASE_OCUPACIONAL_MIN = 1
CLASE_OCUPACIONAL_MAX = 4
EDAD_MIN = 18
EDAD_MAX = 75

VIGENCIA_DIAS = 15


# --- Ayudas de lectura estricta ---------------------------------------------


_AUSENTE: Any = object()


def _exigir(dato: Mapping[str, Any], campo: str) -> Any:
    """Distingue «falta el campo» de «el campo tiene el tipo equivocado».

    Un socio que omite `moneda` y otro que la envía como número merecen mensajes
    distintos: decirle al primero que «debe ser una cadena» le hace buscar un
    error de tipo en un campo que ni siquiera envió.
    """
    valor = dato.get(campo, _AUSENTE)
    if valor is _AUSENTE:
        raise ErrorValidacion(campo, "es obligatorio")
    return valor


def _leer_mapa(dato: Mapping[str, Any], campo: str) -> Mapping[str, Any]:
    valor = _exigir(dato, campo)
    if not isinstance(valor, Mapping):
        raise ErrorValidacion(campo, "debe ser un objeto")
    return valor


def _leer_decimal(dato: Mapping[str, Any], campo: str) -> Decimal:
    valor = _exigir(dato, campo)
    if not isinstance(valor, str):
        raise ErrorValidacion(campo, "debe ser una cadena decimal, no un número JSON")
    try:
        return Decimal(valor)
    except InvalidOperation as err:
        raise ErrorValidacion(campo, "no es un decimal válido") from err


def _leer_entero(dato: Mapping[str, Any], campo: str) -> int:
    valor = _exigir(dato, campo)
    # bool es subclase de int en Python: hay que excluirlo explícitamente.
    if not isinstance(valor, int) or isinstance(valor, bool):
        raise ErrorValidacion(campo, "debe ser un entero")
    return valor


def _leer_bool(dato: Mapping[str, Any], campo: str) -> bool:
    valor = _exigir(dato, campo)
    if not isinstance(valor, bool):
        raise ErrorValidacion(campo, "debe ser booleano")
    return valor


def _leer_texto(dato: Mapping[str, Any], campo: str) -> str:
    valor = _exigir(dato, campo)
    if not isinstance(valor, str):
        raise ErrorValidacion(campo, "debe ser una cadena")
    return valor


def _leer_fecha(dato: Mapping[str, Any], campo: str) -> date:
    crudo = _leer_texto(dato, campo)
    try:
        return date.fromisoformat(crudo)
    except ValueError as err:
        raise ErrorValidacion(campo, "debe tener formato YYYY-MM-DD") from err


def _leer_instante(dato: Mapping[str, Any], campo: str) -> datetime:
    """Lee un instante ISO-8601 en UTC.

    Existe además de `desde_iso_utc` para que un valor malformado produzca un
    422 con el campo nombrado, y no un ValueError que acabe en un 500.
    """
    crudo = _leer_texto(dato, campo)
    try:
        return desde_iso_utc(crudo)
    except ValueError as err:
        raise ErrorValidacion(campo, "debe ser un instante ISO-8601 en UTC") from err


def _leer_enum[E: StrEnum](dato: Mapping[str, Any], campo: str, enumeracion: type[E]) -> E:
    crudo = _leer_texto(dato, campo)
    try:
        return enumeracion(crudo)
    except ValueError as err:
        admitidos = ", ".join(miembro.value for miembro in enumeracion)
        raise ErrorValidacion(campo, f"debe ser uno de: {admitidos}") from err


def _en_rango[T: (int, Decimal)](valor: T, minimo: T, maximo: T, campo: str) -> T:
    if not minimo <= valor <= maximo:
        raise ErrorValidacion(campo, f"debe estar entre {minimo} y {maximo}")
    return valor


def desde_iso_utc(valor: str) -> datetime:
    return datetime.fromisoformat(valor.replace("Z", "+00:00"))


# --- Payload de entrada ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Asegurado:
    fecha_nacimiento: date
    genero: Genero
    fumador: bool
    clase_ocupacional: int

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(
            fecha_nacimiento=_leer_fecha(dato, "fecha_nacimiento"),
            genero=_leer_enum(dato, "genero", Genero),
            fumador=_leer_bool(dato, "fumador"),
            clase_ocupacional=_en_rango(
                _leer_entero(dato, "clase_ocupacional"),
                CLASE_OCUPACIONAL_MIN,
                CLASE_OCUPACIONAL_MAX,
                "asegurado.clase_ocupacional",
            ),
        )

@dataclass(frozen=True, slots=True)
class SolicitudCotizacion:
    producto: Producto
    moneda: Moneda
    suma_asegurada: Decimal
    plazo_meses: int
    canal: Canal
    asegurado: Asegurado
    consentimiento_open_finance: bool

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        """Valida y construye la solicitud, o lanza `ErrorValidacion`.

        La edad no se valida aquí: depende de `fecha_calculo`, que fija Votación
        al normalizar. Se valida en `pricing.calcular`.
        """
        return cls(
            producto=_leer_enum(dato, "producto", Producto),
            moneda=_leer_enum(dato, "moneda", Moneda),
            suma_asegurada=_en_rango(
                _leer_decimal(dato, "suma_asegurada"),
                SUMA_ASEGURADA_MIN,
                SUMA_ASEGURADA_MAX,
                "suma_asegurada",
            ),
            plazo_meses=_en_rango(
                _leer_entero(dato, "plazo_meses"),
                PLAZO_MESES_MIN,
                PLAZO_MESES_MAX,
                "plazo_meses",
            ),
            canal=_leer_enum(dato, "canal", Canal),
            asegurado=Asegurado.desde_dict(_leer_mapa(dato, "asegurado")),
            consentimiento_open_finance=_leer_bool(dato, "consentimiento_open_finance"),
        )

# --- Payload de salida -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Factores:
    fumador: Decimal
    clase_ocupacional: Decimal
    plazo: Decimal
    canal: Decimal

    def a_dict(self) -> dict[str, Any]:
        return {
            "fumador": str(self.fumador),
            "clase_ocupacional": str(self.clase_ocupacional),
            "plazo": str(self.plazo),
            "canal": str(self.canal),
        }


@dataclass(frozen=True, slots=True)
class Explicacion:
    edad_calculada: int
    tasa_base_mil: Decimal
    factores: Factores
    gasto_administrativo: Decimal
    margen: Decimal

    def a_dict(self) -> dict[str, Any]:
        return {
            "edad_calculada": self.edad_calculada,
            "tasa_base_mil": str(self.tasa_base_mil),
            "factores": self.factores.a_dict(),
            "gasto_administrativo": str(self.gasto_administrativo),
            "margen": str(self.margen),
        }


@dataclass(frozen=True, slots=True)
class ResultadoCotizacion:
    moneda: Moneda
    suma_asegurada: Decimal
    prima_mensual: Decimal
    prima_anual: Decimal
    plazo_meses: int
    vigencia_dias: int
    tarifario_version: str
    explicacion: Explicacion

    def a_dict(self) -> dict[str, Any]:
        """Bloques `cotizacion` y `explicacion` de la respuesta pública, juntos."""
        return {
            "moneda": self.moneda.value,
            "suma_asegurada": str(self.suma_asegurada),
            "prima_mensual": str(self.prima_mensual),
            "prima_anual": str(self.prima_anual),
            "plazo_meses": self.plazo_meses,
            "vigencia_dias": self.vigencia_dias,
            "tarifario_version": self.tarifario_version,
            "explicacion": self.explicacion.a_dict(),
        }


# --- Envelope interno (Redis) ------------------------------------------------


@dataclass(frozen=True, slots=True)
class SobreSolicitud:
    """Mensaje que Votación publica en el stream y que leen las tres réplicas.

    `fecha_calculo` se fija aquí, una sola vez, antes del fan-out. Si cada
    réplica consultara su reloj, una petición en el cambio de día podría
    producir edades distintas y una divergencia falsa.
    """

    correlation_id: str
    emitido_en: datetime
    fecha_calculo: date
    payload: SolicitudCotizacion
    tipo: str = "cotizacion.solicitada"
    version: str = "1"

    @classmethod
    def desde_dict(cls, dato: Mapping[str, Any]) -> Self:
        return cls(
            correlation_id=_leer_texto(dato, "correlation_id"),
            emitido_en=_leer_instante(dato, "emitido_en"),
            fecha_calculo=_leer_fecha(dato, "fecha_calculo"),
            payload=SolicitudCotizacion.desde_dict(_leer_mapa(dato, "payload")),
            tipo=_leer_texto(dato, "tipo"),
            version=_leer_texto(dato, "version"),
        )

@dataclass(frozen=True, slots=True)
class SobreRespuesta:
    """Resultado de una réplica, depositado en `cot:resp:{correlation_id}`."""

    correlation_id: str
    cotizador_id: str
    estado: EstadoRespuesta
    duracion_ms: int
    resultado: ResultadoCotizacion | None = None
    error: str | None = None
    tipo: str = "cotizacion.calculada"

    def a_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "tipo": self.tipo,
            "cotizador_id": self.cotizador_id,
            "estado": self.estado.value,
            "duracion_ms": self.duracion_ms,
            "resultado": self.resultado.a_dict() if self.resultado is not None else None,
            "error": self.error,
        }
