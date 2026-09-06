"""Escenarios de mayoría sobre el resultado completo, sin reglas de negocio."""

from dataclasses import replace
from decimal import Decimal

import pytest

from votacion.contracts import (
    EstadoCotizacion,
    EstadoRespuesta,
    ResultadoCotizacion,
    SobreRespuesta,
    TipoIncidente,
)
from votacion.votador import acuerdo_maximo, resolver

CORRELATION_ID = "01a05aa8-24a1-753e-b019-a0810d66a3f6"


def respuesta(cotizador_id: str, resultado: ResultadoCotizacion) -> SobreRespuesta:
    return SobreRespuesta(
        correlation_id=CORRELATION_ID,
        cotizador_id=cotizador_id,
        estado=EstadoRespuesta.OK,
        duracion_ms=1,
        resultado=resultado,
    )


def con_prima(base: ResultadoCotizacion, prima: str) -> ResultadoCotizacion:
    mensual = Decimal(prima)
    return replace(base, prima_mensual=mensual, prima_anual=mensual * 12)


def _resolver(respuestas: list[SobreRespuesta]):  # type: ignore[no-untyped-def]
    return resolver(respuestas, quorum=2, replicas_esperadas=3)


def test_tres_iguales_dan_consenso_limpio(sano: ResultadoCotizacion) -> None:
    veredicto = _resolver(
        [respuesta("A", sano), respuesta("B", sano), respuesta("C", sano)]
    )

    assert veredicto.estado is EstadoCotizacion.COTIZADO
    assert veredicto.resultado is not None
    assert veredicto.resultado.prima_mensual == Decimal("90348.41")
    assert veredicto.acuerdo == 3
    assert veredicto.replicas_divergentes == ()
    assert veredicto.tipo_incidente is None


def test_dos_iguales_enmascaran_a_la_divergente(sano: ResultadoCotizacion) -> None:
    mala = con_prima(sano, "103900.67")
    veredicto = _resolver(
        [respuesta("A", sano), respuesta("B", mala), respuesta("C", sano)]
    )

    assert veredicto.estado is EstadoCotizacion.COTIZADO
    assert veredicto.resultado is not None
    assert veredicto.resultado.prima_mensual == Decimal("90348.41")
    assert veredicto.acuerdo == 2
    assert veredicto.replicas_divergentes == ("B",)
    assert veredicto.tipo_incidente is TipoIncidente.DIVERGENCIA_RESULTADO


def test_tres_distintas_no_alcanzan_quorum(sano: ResultadoCotizacion) -> None:
    veredicto = _resolver(
        [
            respuesta("A", sano),
            respuesta("B", con_prima(sano, "103900.67")),
            respuesta("C", con_prima(sano, "80668.22")),
        ]
    )

    assert veredicto.estado is EstadoCotizacion.RECHAZADO
    assert veredicto.resultado is None
    assert veredicto.tipo_incidente is TipoIncidente.SIN_QUORUM


def test_una_sola_respuesta_no_es_suficiente(sano: ResultadoCotizacion) -> None:
    veredicto = _resolver([respuesta("A", sano)])

    assert veredicto.estado is EstadoCotizacion.RECHAZADO
    assert veredicto.acuerdo == 1


def test_sin_respuestas_se_rechaza() -> None:
    veredicto = _resolver([])

    assert veredicto.estado is EstadoCotizacion.RECHAZADO
    assert veredicto.tipo_incidente is TipoIncidente.REPLICA_NO_RESPONDE


def test_un_valor_extremo_solo_es_una_respuesta_divergente(
    sano: ResultadoCotizacion,
) -> None:
    desorbitada = con_prima(sano, "45174205.00")
    veredicto = _resolver(
        [respuesta("A", sano), respuesta("B", desorbitada), respuesta("C", sano)]
    )

    assert veredicto.estado is EstadoCotizacion.COTIZADO
    assert veredicto.resultado is not None
    assert veredicto.resultado.prima_mensual == Decimal("90348.41")
    assert veredicto.replicas_divergentes == ("B",)


def test_dos_replicas_con_el_mismo_valor_forman_mayoria(
    sano: ResultadoCotizacion,
) -> None:
    """Documenta la premisa de la táctica: como máximo falla una réplica."""
    cero = con_prima(sano, "0.00")
    veredicto = _resolver(
        [respuesta("A", sano), respuesta("B", cero), respuesta("C", cero)]
    )

    assert veredicto.estado is EstadoCotizacion.COTIZADO
    assert veredicto.resultado is not None
    assert veredicto.resultado.prima_mensual == Decimal("0.00")
    assert veredicto.acuerdo == 2


def test_respuesta_sin_resultado_no_participa(sano: ResultadoCotizacion) -> None:
    fallida = SobreRespuesta(
        correlation_id=CORRELATION_ID,
        cotizador_id="B",
        estado=EstadoRespuesta.ERROR,
        duracion_ms=2,
        error="cálculo fallido",
    )
    veredicto = _resolver([respuesta("A", sano), fallida, respuesta("C", sano)])

    assert veredicto.estado is EstadoCotizacion.COTIZADO
    assert veredicto.replicas_divergentes == ("B",)
    assert veredicto.tipo_incidente is TipoIncidente.REPLICA_NO_RESPONDE


def test_tarifario_distinto_es_una_divergencia(sano: ResultadoCotizacion) -> None:
    otra_version = replace(sano, tarifario_version="2025.11")
    veredicto = _resolver(
        [respuesta("A", sano), respuesta("B", otra_version), respuesta("C", sano)]
    )

    assert veredicto.estado is EstadoCotizacion.COTIZADO
    assert veredicto.acuerdo == 2
    assert veredicto.replicas_divergentes == ("B",)


@pytest.mark.parametrize(
    "resultado_distinto",
    [
        lambda sano: replace(sano, prima_anual=Decimal("1.00")),
        lambda sano: replace(sano, vigencia_dias=30),
        lambda sano: replace(
            sano,
            explicacion=replace(sano.explicacion, edad_calculada=39),
        ),
        lambda sano: replace(
            sano,
            explicacion=replace(sano.explicacion, tasa_base_mil=Decimal("0.99")),
        ),
        lambda sano: replace(
            sano,
            explicacion=replace(
                sano.explicacion,
                factores=replace(sano.explicacion.factores, fumador=Decimal("9.99")),
            ),
        ),
    ],
    ids=["prima_anual", "vigencia", "edad", "tasa_base", "factor"],
)
def test_cualquier_diferencia_funcional_se_detecta(
    sano: ResultadoCotizacion,
    resultado_distinto,  # type: ignore[no-untyped-def]
) -> None:
    distinto = resultado_distinto(sano)
    assert distinto.prima_mensual == sano.prima_mensual

    veredicto = _resolver(
        [respuesta("A", sano), respuesta("B", distinto), respuesta("C", sano)]
    )

    assert veredicto.estado is EstadoCotizacion.COTIZADO
    assert veredicto.acuerdo == 2
    assert veredicto.replicas_divergentes == ("B",)
    assert veredicto.tipo_incidente is TipoIncidente.DIVERGENCIA_RESULTADO


def test_los_valores_recibidos_quedan_en_la_evidencia(
    sano: ResultadoCotizacion,
) -> None:
    mala = con_prima(sano, "103900.67")
    veredicto = _resolver(
        [respuesta("A", sano), respuesta("B", mala), respuesta("C", sano)]
    )

    por_replica = {
        valor.cotizador_id: (
            valor.resultado.prima_mensual if valor.resultado is not None else None
        )
        for valor in veredicto.valores_recibidos
    }
    assert por_replica == {
        "A": Decimal("90348.41"),
        "B": Decimal("103900.67"),
        "C": Decimal("90348.41"),
    }


def test_el_error_de_una_replica_queda_en_la_evidencia(
    sano: ResultadoCotizacion,
) -> None:
    fallida = SobreRespuesta(
        correlation_id=CORRELATION_ID,
        cotizador_id="B",
        estado=EstadoRespuesta.ERROR,
        duracion_ms=2,
        error="cálculo fallido",
    )

    veredicto = _resolver([respuesta("A", sano), fallida, respuesta("C", sano)])
    evidencia_b = next(
        valor for valor in veredicto.valores_recibidos if valor.cotizador_id == "B"
    )

    assert evidencia_b.resultado is None
    assert evidencia_b.error == "cálculo fallido"


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
    sano: ResultadoCotizacion,
    primas: list[str],
    acuerdo: int,
) -> None:
    respuestas = [respuesta(chr(65 + i), con_prima(sano, prima)) for i, prima in enumerate(primas)]
    assert acuerdo_maximo(respuestas) == acuerdo
