"""Reporte de incidentes para lectura humana.

Convierte la evidencia cruda del JSONL en un modelo de vista que responde tres
preguntas por registro: qué se detectó, cuándo ocurrió y cómo se manifestó (qué
devolvió cada réplica y en qué campos difieren). Aquí no hay HTML: la plantilla
solo recorre estas estructuras.

Trabaja sobre los diccionarios persistidos y no sobre `Incidente` a propósito:
el fichero puede contener registros escritos por versiones anteriores del
contrato, y un reporte no puede negarse a mostrar evidencia por un campo de más
o de menos. Lo que no entiende lo muestra tal cual, nunca lo oculta.
"""

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from gestion_errores.contracts import TipoIncidente

#: Marca de "sin valor" en las celdas. Un guion largo se lee mejor que "None"
#: o una celda vacía en una tabla impresa.
NO_APLICA = "—"

#: Claves de un valor recibido que no son datos comparables: identifican a la
#: réplica o describen su fallo, y tienen su propio sitio en el reporte.
_CLAVES_PROPIAS = frozenset({"cotizador_id", "resultado", "error"})


@dataclass(frozen=True, slots=True)
class DescripcionTipo:
    etiqueta: str
    explicacion: str


_TIPOS: dict[TipoIncidente, DescripcionTipo] = {
    TipoIncidente.DIVERGENCIA_RESULTADO: DescripcionTipo(
        etiqueta="Divergencia de resultado",
        explicacion=(
            "Las réplicas del cotizador respondieron con resultados distintos a la "
            "misma solicitud. La mayoría fijó el valor entregado y la minoría quedó "
            "señalada como divergente."
        ),
    ),
    TipoIncidente.SIN_QUORUM: DescripcionTipo(
        etiqueta="Sin quórum",
        explicacion=(
            "Ninguna coincidencia entre réplicas alcanzó el quórum exigido, por lo que "
            "no fue posible emitir una cotización respaldada por consenso."
        ),
    ),
    TipoIncidente.REPLICA_NO_RESPONDE: DescripcionTipo(
        etiqueta="Réplica sin respuesta",
        explicacion=(
            "Una o más réplicas no respondieron dentro del tiempo límite establecido "
            "para la votación."
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class Celda:
    cotizador_id: str
    valor: str
    #: Distinto del valor mayoritario entre las réplicas que sí respondieron.
    difiere: bool


@dataclass(frozen=True, slots=True)
class CampoComparado:
    nombre: str
    celdas: tuple[Celda, ...]
    difiere: bool


@dataclass(frozen=True, slots=True)
class ReplicaReporte:
    cotizador_id: str
    respondio: bool
    error: str | None
    #: Marcada por Votación como discrepante del consenso.
    divergente: bool


@dataclass(frozen=True, slots=True)
class IncidenteReporte:
    correlation_id: str
    # --- Qué ---------------------------------------------------------------
    tipo: str
    tipo_etiqueta: str
    tipo_explicacion: str
    replicas_divergentes: tuple[str, ...]
    campos_divergentes: tuple[str, ...]
    detalle: str | None
    # --- Cuándo ------------------------------------------------------------
    detectado_en_iso: str
    detectado_en_texto: str
    # --- Cómo --------------------------------------------------------------
    replicas: tuple[ReplicaReporte, ...]
    comparacion: tuple[CampoComparado, ...]


@dataclass(frozen=True, slots=True)
class Reporte:
    generado_en_iso: str
    generado_en_texto: str
    filtro_correlation_id: str | None
    total: int
    por_tipo: tuple[tuple[str, int], ...]
    por_replica: tuple[tuple[str, int], ...]
    #: Del más reciente al más antiguo: quien abre un reporte de incidentes
    #: quiere ver primero lo último que pasó.
    incidentes: tuple[IncidenteReporte, ...]


def construir(
    incidentes: Sequence[Mapping[str, Any]],
    *,
    filtro_correlation_id: str | None = None,
    generado_en: datetime | None = None,
) -> Reporte:
    """Modelo de vista del reporte a partir de los incidentes tal como se leyeron."""
    ahora = generado_en or datetime.now(UTC)
    filas = tuple(_fila(incidente) for incidente in reversed(incidentes))
    por_tipo = Counter(fila.tipo_etiqueta for fila in filas)
    por_replica = Counter(replica for fila in filas for replica in fila.replicas_divergentes)
    return Reporte(
        generado_en_iso=_iso(ahora),
        generado_en_texto=_texto_instante(ahora),
        filtro_correlation_id=filtro_correlation_id,
        total=len(filas),
        por_tipo=_ordenar_conteo(por_tipo),
        por_replica=_ordenar_conteo(por_replica),
        incidentes=filas,
    )


def _ordenar_conteo(conteo: Counter[str]) -> tuple[tuple[str, int], ...]:
    """De mayor a menor; a igual cifra, alfabético para que el orden sea estable."""
    return tuple(sorted(conteo.items(), key=lambda par: (-par[1], par[0])))


def _fila(dato: Mapping[str, Any]) -> IncidenteReporte:
    tipo = str(dato.get("tipo") or "")
    descripcion = _describir(tipo)
    divergentes = tuple(str(replica) for replica in _lista(dato.get("replicas_divergentes")))
    valores = tuple(
        valor for valor in _lista(dato.get("valores_recibidos")) if isinstance(valor, Mapping)
    )
    comparacion = _comparar(valores)
    detectado_iso, detectado_texto = _instante(dato.get("detectado_en"))
    detalle = dato.get("detalle")
    return IncidenteReporte(
        correlation_id=str(dato.get("correlation_id") or NO_APLICA),
        tipo=tipo,
        tipo_etiqueta=descripcion.etiqueta,
        tipo_explicacion=descripcion.explicacion,
        replicas_divergentes=divergentes,
        campos_divergentes=tuple(campo.nombre for campo in comparacion if campo.difiere),
        detalle=detalle if isinstance(detalle, str) and detalle else None,
        detectado_en_iso=detectado_iso,
        detectado_en_texto=detectado_texto,
        replicas=tuple(_replica(valor, divergentes) for valor in valores),
        comparacion=comparacion,
    )


def _describir(tipo: str) -> DescripcionTipo:
    try:
        return _TIPOS[TipoIncidente(tipo)]
    except ValueError:
        return DescripcionTipo(
            etiqueta=tipo or "Tipo desconocido",
            explicacion=(
                "Tipo de incidente que esta versión del servicio no reconoce; se muestra "
                "tal como quedó registrado."
            ),
        )


def _lista(crudo: object) -> list[Any]:
    return crudo if isinstance(crudo, list) else []


def _replica(valor: Mapping[str, Any], divergentes: tuple[str, ...]) -> ReplicaReporte:
    cotizador_id = str(valor.get("cotizador_id") or "?")
    error = valor.get("error")
    error_texto = error if isinstance(error, str) and error else None
    return ReplicaReporte(
        cotizador_id=cotizador_id,
        respondio=error_texto is None,
        error=error_texto,
        divergente=cotizador_id in divergentes,
    )


def _comparar(valores: Sequence[Mapping[str, Any]]) -> tuple[CampoComparado, ...]:
    """Tabla campo por réplica con las diferencias señaladas.

    Una réplica sin valor para un campo (porque falló, o porque devolvió otra
    forma) no cuenta como diferencia: su fallo ya aparece en el estado de la
    réplica, y marcar todas sus celdas ahogaría la diferencia real.
    """
    ids = [str(valor.get("cotizador_id") or "?") for valor in valores]
    planos = [_aplanar_valor(valor) for valor in valores]
    nombres = list(dict.fromkeys(nombre for plano in planos for nombre in plano))

    campos: list[CampoComparado] = []
    for nombre in nombres:
        textos = [plano.get(nombre, NO_APLICA) for plano in planos]
        presentes = [texto for texto in textos if texto != NO_APLICA]
        conteo = Counter(presentes)
        celdas = tuple(
            Celda(cotizador_id=cotizador_id, valor=texto, difiere=_difiere(texto, conteo))
            for cotizador_id, texto in zip(ids, textos, strict=True)
        )
        campos.append(
            CampoComparado(
                nombre=nombre,
                celdas=celdas,
                difiere=any(celda.difiere for celda in celdas),
            )
        )
    return tuple(campos)


def _difiere(texto: str, conteo: Counter[str]) -> bool:
    """Con mayoría estricta se señala a la minoría; sin ella, a todas las que no coinciden."""
    if texto == NO_APLICA or len(conteo) < 2:
        return False
    mayoritario, veces = conteo.most_common(1)[0]
    if veces * 2 > sum(conteo.values()):
        return texto != mayoritario
    return True


def _aplanar_valor(valor: Mapping[str, Any]) -> dict[str, str]:
    """Campos comparables de una réplica, con las claves anidadas unidas por puntos.

    El `resultado` se aplana sin prefijo porque es la cotización en sí. Cualquier
    otra clave que no sea propia del sobre (p. ej. un `prima_mensual` suelto de
    otra versión del contrato) también entra: es evidencia y se compara igual.
    """
    plano: dict[str, str] = {}
    resultado = valor.get("resultado")
    if isinstance(resultado, Mapping):
        _aplanar(resultado, "", plano)
    extras = {clave: crudo for clave, crudo in valor.items() if clave not in _CLAVES_PROPIAS}
    _aplanar(extras, "", plano)
    return plano


def _aplanar(datos: Mapping[str, Any], prefijo: str, destino: dict[str, str]) -> None:
    for clave, crudo in datos.items():
        nombre = f"{prefijo}.{clave}" if prefijo else str(clave)
        if isinstance(crudo, Mapping):
            _aplanar(crudo, nombre, destino)
        else:
            destino[nombre] = _texto(crudo)


def _texto(crudo: object) -> str:
    if crudo is None:
        return NO_APLICA
    if isinstance(crudo, bool):
        return "sí" if crudo else "no"
    if isinstance(crudo, list | tuple):
        return json.dumps(crudo, ensure_ascii=False)
    return str(crudo)


def _instante(crudo: object) -> tuple[str, str]:
    """(ISO-8601 en UTC, texto legible). Si no se puede interpretar, se muestra crudo."""
    if not isinstance(crudo, str) or not crudo:
        return "", NO_APLICA
    try:
        instante = datetime.fromisoformat(crudo)
    except ValueError:
        return "", crudo
    if instante.tzinfo is None:
        return "", crudo
    return _iso(instante), _texto_instante(instante)


def _iso(instante: datetime) -> str:
    return instante.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _texto_instante(instante: datetime) -> str:
    utc = instante.astimezone(UTC)
    return f"{utc:%d/%m/%Y %H:%M:%S}.{utc.microsecond // 1000:03d} UTC"
