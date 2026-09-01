"""Los escenarios de la votación, como funciones puras: sin Redis ni Flask.

Cada caso corresponde a una fila del comportamiento esperado de ASR-11/ASR-12.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from solventa_common.contracts import (
    EstadoCotizacion,
    EstadoRespuesta,
    ResultadoCotizacion,
    SobreRespuesta,
    SolicitudCotizacion,
    TipoIncidente,
)
from solventa_common.hashing import resultado_hash
from solventa_common.pricing import redondear
from votacion.votador import acuerdo_maximo, resolver

VERSION = "2026.02"
FECHA_CALCULO = date(2026, 8, 31)
CORRELATION_ID = "01a05aa8-24a1-753e-b019-a0810d66a3f6"


def respuesta(cotizador_id: str, resultado: ResultadoCotizacion) -> SobreRespuesta:
    """Sobre de respuesta sano para una réplica."""
    return SobreRespuesta(
        correlation_id=CORRELATION_ID,
        cotizador_id=cotizador_id,
        estado=EstadoRespuesta.OK,
        duracion_ms=1,
        resultado_hash=resultado_hash(resultado),
        resultado=resultado,
    )


def con_prima(base: ResultadoCotizacion, prima: str) -> ResultadoCotizacion:
    """Copia el resultado con otra prima, manteniendo coherente la anual.

    La coherencia importa: si la anual quedara descuadrada, la regla
    `coherencia_anual` detectaría el caso por sí sola y el test dejaría de
    probar lo que dice probar.
    """
    mensual = Decimal(prima)
    return replace(base, prima_mensual=mensual, prima_anual=redondear(mensual * 12))


def _resolver(respuestas: list[SobreRespuesta], solicitud: SolicitudCotizacion):  # type: ignore[no-untyped-def]
    return resolver(
        respuestas,
        solicitud,
        tarifario_esperado=VERSION,
        quorum=2,
        replicas_esperadas=3,
    )


# --- 1. Tres iguales ---------------------------------------------------------


def test_tres_iguales_dan_consenso_limpio(
    solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    veredicto = _resolver(
        [respuesta("A", sano), respuesta("B", sano), respuesta("C", sano)], solicitud
    )

    assert veredicto.estado is EstadoCotizacion.COTIZADO
    assert veredicto.resultado is not None
    assert veredicto.resultado.prima_mensual == Decimal("90348.41")
    assert veredicto.acuerdo == 3
    assert veredicto.replicas_divergentes == ()
    assert veredicto.tipo_incidente is None
    assert veredicto.hubo_divergencia is False


# --- 2. Dos iguales y una divergente (el caso central de ASR-12) -------------


def test_dos_iguales_enmascaran_a_la_divergente(
    solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    """El cliente recibe el valor CORRECTO pese al fallo activo en B."""
    mala = con_prima(sano, "103900.67")
    veredicto = _resolver(
        [respuesta("A", sano), respuesta("B", mala), respuesta("C", sano)], solicitud
    )

    assert veredicto.estado is EstadoCotizacion.COTIZADO
    assert veredicto.resultado is not None
    assert veredicto.resultado.prima_mensual == Decimal("90348.41")
    assert veredicto.acuerdo == 2
    assert veredicto.replicas_divergentes == ("B",)
    assert veredicto.tipo_incidente is TipoIncidente.DIVERGENCIA_RESULTADO


# --- 3. Tres distintas -------------------------------------------------------


def test_tres_distintas_no_alcanzan_quorum(
    solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    """Todas válidas pero ninguna coincide: no hay valor en el que confiar."""
    veredicto = _resolver(
        [
            respuesta("A", sano),
            respuesta("B", con_prima(sano, "103900.67")),
            respuesta("C", con_prima(sano, "80668.22")),
        ],
        solicitud,
    )

    assert veredicto.estado is EstadoCotizacion.RECHAZADO
    assert veredicto.resultado is None
    assert veredicto.tipo_incidente is TipoIncidente.SIN_QUORUM


# --- 4. Una sola respuesta ---------------------------------------------------


def test_una_sola_respuesta_es_degradada(
    solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    """Se responde porque es preferible a rechazar, pero sin segunda opinión."""
    veredicto = _resolver([respuesta("A", sano)], solicitud)

    assert veredicto.estado is EstadoCotizacion.COTIZADO_DEGRADADO
    assert veredicto.resultado is not None
    assert veredicto.resultado.prima_mensual == Decimal("90348.41")
    assert veredicto.acuerdo == 1
    assert veredicto.tipo_incidente is TipoIncidente.REPLICA_NO_RESPONDE


# --- 5. Ninguna respuesta ----------------------------------------------------


def test_sin_respuestas_se_rechaza(solicitud: SolicitudCotizacion) -> None:
    veredicto = _resolver([], solicitud)

    assert veredicto.estado is EstadoCotizacion.RECHAZADO
    assert veredicto.respuestas_recibidas == 0
    assert veredicto.tipo_incidente is TipoIncidente.REPLICA_NO_RESPONDE


# --- 6. Una inválida y dos iguales -------------------------------------------


def test_una_invalida_se_descarta_y_las_otras_dos_deciden(
    solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    """`out_of_range`: la regla de rango la elimina antes de agrupar."""
    desorbitada = con_prima(sano, "45174205.00")
    veredicto = _resolver(
        [respuesta("A", sano), respuesta("B", desorbitada), respuesta("C", sano)],
        solicitud,
    )

    assert veredicto.estado is EstadoCotizacion.COTIZADO
    assert veredicto.resultado is not None
    assert veredicto.resultado.prima_mensual == Decimal("90348.41")
    assert veredicto.replicas_divergentes == ("B",)
    # Prevalece la regla de validez sobre la divergencia: es más específica.
    assert veredicto.tipo_incidente is TipoIncidente.REGLA_DE_VALIDEZ
    assert veredicto.detalle is not None
    assert "ratio_prima_suma" in veredicto.detalle


# --- Casos adicionales -------------------------------------------------------


def test_dos_invalidas_no_pueden_formar_mayoria(
    solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    """Dos réplicas rotas del MISMO modo producen la misma huella.

    Si se agrupara antes de cribar, formarían quórum sobre un valor imposible y
    el sistema respondería con él. Cribar primero es lo que lo impide.
    """
    cero = con_prima(sano, "0.00")
    veredicto = _resolver(
        [respuesta("A", sano), respuesta("B", cero), respuesta("C", cero)], solicitud
    )

    assert veredicto.estado is EstadoCotizacion.COTIZADO_DEGRADADO
    assert veredicto.resultado is not None
    assert veredicto.resultado.prima_mensual == Decimal("90348.41")
    assert set(veredicto.replicas_divergentes) == {"B", "C"}
    assert veredicto.tipo_incidente is TipoIncidente.REGLA_DE_VALIDEZ


def test_respuesta_de_error_cuenta_como_invalida(
    solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    fallida = SobreRespuesta(
        correlation_id="x",
        cotizador_id="B",
        estado=EstadoRespuesta.ERROR,
        duracion_ms=2,
        error="cálculo fallido",
    )
    veredicto = _resolver([respuesta("A", sano), fallida, respuesta("C", sano)], solicitud)

    assert veredicto.estado is EstadoCotizacion.COTIZADO
    assert veredicto.replicas_divergentes == ("B",)


def test_tarifario_desactualizado_se_descarta(
    solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    from solventa_common.pricing import calcular

    stale = calcular(solicitud, FECHA_CALCULO, "2025.11")
    veredicto = _resolver(
        [respuesta("A", sano), respuesta("B", stale), respuesta("C", sano)], solicitud
    )

    assert veredicto.estado is EstadoCotizacion.COTIZADO
    assert veredicto.replicas_divergentes == ("B",)
    assert veredicto.tipo_incidente is TipoIncidente.REGLA_DE_VALIDEZ


def test_los_valores_recibidos_quedan_registrados(
    solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    """Es la evidencia que va al incidente: qué respondió cada réplica."""
    mala = con_prima(sano, "103900.67")
    veredicto = _resolver(
        [respuesta("A", sano), respuesta("B", mala), respuesta("C", sano)], solicitud
    )

    por_replica = {v.cotizador_id: v.prima_mensual for v in veredicto.valores_recibidos}
    assert por_replica == {
        "A": Decimal("90348.41"),
        "B": Decimal("103900.67"),
        "C": Decimal("90348.41"),
    }


# --- Corte anticipado --------------------------------------------------------


@pytest.mark.parametrize(
    ("primas", "acuerdo"),
    [
        ([], 0),
        (["90348.41"], 1),
        (["90348.41", "103900.67"], 1),
        (["90348.41", "90348.41"], 2),
        (["90348.41", "90348.41", "90348.41"], 3),
    ],
)
def test_acuerdo_maximo(
    solicitud: SolicitudCotizacion,
    sano: ResultadoCotizacion,
    primas: list[str],
    acuerdo: int,
) -> None:
    respuestas = [respuesta(chr(65 + i), con_prima(sano, p)) for i, p in enumerate(primas)]
    assert acuerdo_maximo(respuestas, solicitud, VERSION) == acuerdo


def test_dos_invalidas_iguales_no_cuentan_como_acuerdo(
    solicitud: SolicitudCotizacion, sano: ResultadoCotizacion
) -> None:
    """Si contaran, el recolector cortaría antes de leer a la réplica sana."""
    cero = con_prima(sano, "0.00")
    respuestas = [respuesta("B", cero), respuesta("C", cero)]

    assert acuerdo_maximo(respuestas, solicitud, VERSION) == 0
