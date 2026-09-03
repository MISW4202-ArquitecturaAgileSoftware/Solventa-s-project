"""Las cuatro reglas de validez (§2.4), que son la detección de ASR-11 con una
sola respuesta disponible."""

from dataclasses import replace
from decimal import Decimal

import pytest

from cotizador.common.contracts import SolicitudCotizacion
from cotizador.common.pricing import calcular, validar

from .conftest import FECHA_CALCULO


def test_resultado_sano_no_tiene_violaciones(
    solicitud_canonica: SolicitudCotizacion,
) -> None:
    resultado = calcular(solicitud_canonica, FECHA_CALCULO)
    assert validar(resultado, solicitud_canonica) == []


def test_prima_cero_viola_positividad_y_ratio(
    solicitud_canonica: SolicitudCotizacion,
) -> None:
    """Corresponde al modo de fallo `silent_zero`."""
    sano = calcular(solicitud_canonica, FECHA_CALCULO)
    roto = replace(sano, prima_mensual=Decimal("0.00"), prima_anual=Decimal("0.00"))

    reglas = {v.regla for v in validar(roto, solicitud_canonica)}
    assert "prima_positiva" in reglas
    assert "ratio_prima_suma" in reglas


def test_prima_desorbitada_viola_el_ratio(
    solicitud_canonica: SolicitudCotizacion,
) -> None:
    """Corresponde al modo de fallo `out_of_range`."""
    sano = calcular(solicitud_canonica, FECHA_CALCULO)
    inflada = sano.prima_mensual * 500
    roto = replace(sano, prima_mensual=inflada, prima_anual=inflada * 12)

    reglas = {v.regla for v in validar(roto, solicitud_canonica)}
    assert reglas == {"ratio_prima_suma"}


def test_anual_incoherente_se_detecta(solicitud_canonica: SolicitudCotizacion) -> None:
    sano = calcular(solicitud_canonica, FECHA_CALCULO)
    roto = replace(sano, prima_anual=sano.prima_anual + Decimal("1.00"))

    reglas = {v.regla for v in validar(roto, solicitud_canonica)}
    assert reglas == {"coherencia_anual"}


def test_tarifario_desactualizado_se_detecta(
    solicitud_canonica: SolicitudCotizacion,
) -> None:
    """Corresponde al modo de fallo `rate_table_stale`."""
    stale = calcular(solicitud_canonica, FECHA_CALCULO, "2025.11")

    reglas = {v.regla for v in validar(stale, solicitud_canonica, "2026.02")}
    assert "tarifario_vigente" in reglas


@pytest.mark.parametrize("factor", [Decimal("1.15"), Decimal("0.85")])
def test_desvio_moderado_no_lo_detecta_una_regla_de_rango(
    solicitud_canonica: SolicitudCotizacion, factor: Decimal
) -> None:
    """Límite deliberado y documentado del diseño.

    `premium_offset` (±15 %) queda dentro de las cotas de ratio: ninguna regla
    estructural puede verlo. Solo lo detecta la divergencia de hash entre
    réplicas. Este test fija esa frontera para que nadie la borre por accidente.
    """
    from cotizador.common.pricing import redondear

    sano = calcular(solicitud_canonica, FECHA_CALCULO)
    desviada = redondear(sano.prima_mensual * factor)
    roto = replace(sano, prima_mensual=desviada, prima_anual=redondear(desviada * 12))

    assert validar(roto, solicitud_canonica) == []
