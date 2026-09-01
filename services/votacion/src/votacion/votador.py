"""Resolución del veredicto: lógica pura, sin Redis ni Flask.

Aquí es donde se cumplen ASR-11 y ASR-12, y por eso está aislado de toda E/S:
los seis escenarios que importan —tres iguales, dos y una divergente, tres
distintas, una sola, ninguna, y una inválida con dos iguales— se prueban como
funciones puras, sin levantar nada.

El orden de resolución no es negociable y va en este orden por una razón:
descartar primero lo estructuralmente imposible evita que dos réplicas
igualmente rotas formen mayoría sobre un valor inválido.
"""

from collections import defaultdict
from dataclasses import dataclass

from solventa_common.contracts import (
    EstadoCotizacion,
    ResultadoCotizacion,
    SobreRespuesta,
    SolicitudCotizacion,
    TipoIncidente,
    ValorRecibido,
)
from solventa_common.pricing import Violacion, validar


@dataclass(frozen=True, slots=True)
class Veredicto:
    estado: EstadoCotizacion
    resultado: ResultadoCotizacion | None
    respuestas_recibidas: int
    #: Tamaño del grupo ganador: cuántas réplicas coincidieron en el valor.
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
        resultado_hash=respuesta.resultado_hash,
    )


def _cribar(
    respuestas: list[SobreRespuesta],
    solicitud: SolicitudCotizacion,
    tarifario_esperado: str,
) -> tuple[list[SobreRespuesta], dict[str, list[Violacion]]]:
    """Separa lo estructuralmente posible de lo que no lo es (§2.4)."""
    validas: list[SobreRespuesta] = []
    invalidas: dict[str, list[Violacion]] = {}
    for respuesta in respuestas:
        if respuesta.resultado is None or respuesta.resultado_hash is None:
            invalidas[respuesta.cotizador_id] = [
                Violacion("respuesta_incompleta", respuesta.error or "sin resultado")
            ]
            continue
        violaciones = validar(respuesta.resultado, solicitud, tarifario_esperado)
        if violaciones:
            invalidas[respuesta.cotizador_id] = violaciones
        else:
            validas.append(respuesta)
    return validas, invalidas


def _mayor_grupo(validas: list[SobreRespuesta]) -> list[SobreRespuesta]:
    grupos: dict[str, list[SobreRespuesta]] = defaultdict(list)
    for respuesta in validas:
        if respuesta.resultado_hash is not None:
            grupos[respuesta.resultado_hash].append(respuesta)
    return max(grupos.values(), key=len, default=[])


def acuerdo_maximo(
    respuestas: list[SobreRespuesta],
    solicitud: SolicitudCotizacion,
    tarifario_esperado: str,
) -> int:
    """Cuántas réplicas VÁLIDAS coinciden ya en un mismo valor.

    Lo usa el recolector para cortar en cuanto hay quórum. Se criba antes de
    contar a propósito: dos réplicas igualmente rotas producen la misma huella,
    y contarlas como acuerdo cortaría la recolección para formar mayoría sobre
    un valor que después se descarta.
    """
    validas, _ = _cribar(respuestas, solicitud, tarifario_esperado)
    return len(_mayor_grupo(validas))


def resolver(
    respuestas: list[SobreRespuesta],
    solicitud: SolicitudCotizacion,
    *,
    tarifario_esperado: str,
    quorum: int,
    replicas_esperadas: int,
) -> Veredicto:
    valores = tuple(_valor_recibido(r) for r in respuestas)
    faltan = replicas_esperadas - len(respuestas)

    # --- 1. Descartar lo estructuralmente imposible --------------------------
    validas, invalidas = _cribar(respuestas, solicitud, tarifario_esperado)

    # --- 2. Agrupar supervivientes por huella --------------------------------
    mayor = _mayor_grupo(validas)
    ganadores = {r.cotizador_id for r in mayor}
    divergentes = tuple(
        sorted(r.cotizador_id for r in respuestas if r.cotizador_id not in ganadores)
    )

    detalle = _detallar(invalidas, faltan)

    # --- 3. Veredicto --------------------------------------------------------
    if len(mayor) >= quorum:
        return Veredicto(
            estado=EstadoCotizacion.COTIZADO,
            resultado=mayor[0].resultado,
            respuestas_recibidas=len(respuestas),
            acuerdo=len(mayor),
            replicas_divergentes=divergentes,
            tipo_incidente=_clasificar(invalidas, divergentes, faltan, sin_quorum=False),
            detalle=detalle,
            valores_recibidos=valores,
        )

    if len(validas) == 1:
        # Una sola superviviente: se responde con ella porque es preferible a
        # rechazar, pero se marca degradado. No hay segunda opinión que la
        # confirme, solo las reglas de validez.
        return Veredicto(
            estado=EstadoCotizacion.COTIZADO_DEGRADADO,
            resultado=validas[0].resultado,
            respuestas_recibidas=len(respuestas),
            acuerdo=1,
            replicas_divergentes=divergentes,
            tipo_incidente=_clasificar(invalidas, divergentes, faltan, sin_quorum=False),
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
        detalle=detalle or "ninguna coincidencia alcanzó el quórum",
        valores_recibidos=valores,
    )


def _clasificar(
    invalidas: dict[str, list[Violacion]],
    divergentes: tuple[str, ...],
    faltan: int,
    *,
    sin_quorum: bool,
) -> TipoIncidente | None:
    """Un incidente por journey, con el tipo más específico que aplique.

    Uno y no varios porque el denominador de ASR-11 es el número de fallos
    inyectados: si un solo fallo generara tres incidentes, la tasa de detección
    saldría inflada.
    """
    if sin_quorum:
        return TipoIncidente.SIN_QUORUM
    if invalidas:
        return TipoIncidente.REGLA_DE_VALIDEZ
    if divergentes:
        return TipoIncidente.DIVERGENCIA_RESULTADO
    if faltan > 0:
        return TipoIncidente.REPLICA_NO_RESPONDE
    return None


def _detallar(invalidas: dict[str, list[Violacion]], faltan: int) -> str | None:
    partes = [
        f"{cotizador}: {', '.join(v.regla for v in violaciones)}"
        for cotizador, violaciones in sorted(invalidas.items())
    ]
    if faltan > 0:
        partes.append(f"{faltan} réplica(s) sin responder")
    return "; ".join(partes) or None
