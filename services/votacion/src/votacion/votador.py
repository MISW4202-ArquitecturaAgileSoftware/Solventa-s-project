"""Decisión por mayoría, sin reglas de cálculo ni dependencias externas."""

from collections import defaultdict
from dataclasses import dataclass

from votacion.contracts import (
    EstadoCotizacion,
    ResultadoCotizacion,
    SobreRespuesta,
    TipoIncidente,
    ValorRecibido,
)


@dataclass(frozen=True, slots=True)
class Veredicto:
    estado: EstadoCotizacion
    resultado: ResultadoCotizacion | None
    respuestas_recibidas: int
    acuerdo: int
    replicas_divergentes: tuple[str, ...]
    tipo_incidente: TipoIncidente | None
    detalle: str | None
    valores_recibidos: tuple[ValorRecibido, ...]

    @property
    def hubo_divergencia(self) -> bool:
        return bool(self.replicas_divergentes) or self.tipo_incidente is not None


def _valor_recibido(respuesta: SobreRespuesta) -> ValorRecibido:
    return ValorRecibido(
        cotizador_id=respuesta.cotizador_id,
        prima_mensual=respuesta.resultado.prima_mensual if respuesta.resultado else None,
    )


def _respuestas_con_resultado(
    respuestas: list[SobreRespuesta],
) -> tuple[list[SobreRespuesta], tuple[str, ...]]:
    utilizables = [respuesta for respuesta in respuestas if respuesta.resultado is not None]
    sin_resultado = tuple(
        sorted(respuesta.cotizador_id for respuesta in respuestas if respuesta.resultado is None)
    )
    return utilizables, sin_resultado


def _mayor_grupo(respuestas: list[SobreRespuesta]) -> list[SobreRespuesta]:
    """Agrupa por el resultado funcional completo que devolvió cada réplica."""
    grupos: dict[ResultadoCotizacion, list[SobreRespuesta]] = defaultdict(list)
    for respuesta in respuestas:
        if respuesta.resultado is not None:
            grupos[respuesta.resultado].append(respuesta)
    return max(grupos.values(), key=len, default=[])


def acuerdo_maximo(respuestas: list[SobreRespuesta]) -> int:
    """Mayor cantidad de réplicas que coinciden en todo el resultado."""
    utilizables, _ = _respuestas_con_resultado(respuestas)
    return len(_mayor_grupo(utilizables))


def resolver(
    respuestas: list[SobreRespuesta],
    *,
    quorum: int,
    replicas_esperadas: int,
) -> Veredicto:
    valores = tuple(_valor_recibido(respuesta) for respuesta in respuestas)
    faltan = max(0, replicas_esperadas - len(respuestas))
    utilizables, sin_resultado = _respuestas_con_resultado(respuestas)
    mayor = _mayor_grupo(utilizables)
    ganadores = {respuesta.cotizador_id for respuesta in mayor}
    divergentes = tuple(
        sorted(
            respuesta.cotizador_id
            for respuesta in respuestas
            if respuesta.cotizador_id not in ganadores
        )
    )
    detalle = _detalle(sin_resultado, faltan)

    if len(mayor) >= quorum:
        return Veredicto(
            estado=EstadoCotizacion.COTIZADO,
            resultado=mayor[0].resultado,
            respuestas_recibidas=len(respuestas),
            acuerdo=len(mayor),
            replicas_divergentes=divergentes,
            tipo_incidente=_clasificar(sin_resultado, divergentes, faltan),
            detalle=detalle,
            valores_recibidos=valores,
        )

    if not respuestas:
        return Veredicto(
            estado=EstadoCotizacion.RECHAZADO,
            resultado=None,
            respuestas_recibidas=0,
            acuerdo=0,
            replicas_divergentes=(),
            tipo_incidente=TipoIncidente.REPLICA_NO_RESPONDE,
            detalle=f"ninguna de las {replicas_esperadas} réplicas respondió a tiempo",
            valores_recibidos=(),
        )

    return Veredicto(
        estado=EstadoCotizacion.RECHAZADO,
        resultado=None,
        respuestas_recibidas=len(respuestas),
        acuerdo=len(mayor),
        replicas_divergentes=divergentes,
        tipo_incidente=TipoIncidente.SIN_QUORUM,
        detalle=detalle or "ningún resultado completo alcanzó el quórum",
        valores_recibidos=valores,
    )


def _clasificar(
    sin_resultado: tuple[str, ...],
    divergentes: tuple[str, ...],
    faltan: int,
) -> TipoIncidente | None:
    if sin_resultado or faltan > 0:
        return TipoIncidente.REPLICA_NO_RESPONDE
    if divergentes:
        return TipoIncidente.DIVERGENCIA_RESULTADO
    return None


def _detalle(sin_resultado: tuple[str, ...], faltan: int) -> str | None:
    partes: list[str] = []
    if sin_resultado:
        partes.append(f"sin resultado: {', '.join(sin_resultado)}")
    if faltan > 0:
        partes.append(f"{faltan} réplica(s) sin responder")
    return "; ".join(partes) or None
