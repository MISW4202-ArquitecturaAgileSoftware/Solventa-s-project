"""El ejemplo canónico y las propiedades del cálculo."""

from datetime import date
from decimal import Decimal

import pytest

from solventa_common import tarifario
from solventa_common.contracts import (
    Asegurado,
    Canal,
    Genero,
    Moneda,
    Producto,
    SolicitudCotizacion,
)
from solventa_common.errors import ErrorValidacion
from solventa_common.pricing import calcular, edad_cumplida

from .conftest import FECHA_CALCULO


def test_ejemplo_canonico(solicitud_canonica: SolicitudCotizacion) -> None:
    """Criterio de cierre de F1. Si este número cambia, todo el plan cambia."""
    resultado = calcular(solicitud_canonica, FECHA_CALCULO)

    assert resultado.prima_mensual == Decimal("90348.41")
    assert resultado.prima_anual == Decimal("1084180.92")
    assert resultado.explicacion.edad_calculada == 38
    assert resultado.explicacion.tasa_base_mil == Decimal("0.26")
    assert resultado.tarifario_version == "2026.02"
    assert resultado.vigencia_dias == 15


def test_factores_del_ejemplo_canonico(solicitud_canonica: SolicitudCotizacion) -> None:
    factores = calcular(solicitud_canonica, FECHA_CALCULO).explicacion.factores

    assert factores.fumador == Decimal("1.00")
    assert factores.clase_ocupacional == Decimal("1.12")
    assert factores.plazo == Decimal("1.08")
    assert factores.canal == Decimal("0.95")


@pytest.mark.parametrize(
    ("nacimiento", "calculo", "esperada"),
    [
        (date(1988, 4, 17), date(2026, 8, 31), 38),
        # Víspera del cumpleaños: aún no los ha cumplido.
        (date(1988, 4, 17), date(2026, 4, 16), 37),
        # El mismo día del cumpleaños sí cuenta.
        (date(1988, 4, 17), date(2026, 4, 17), 38),
        # 29 de febrero: el año no bisiesto no debe adelantar la edad.
        (date(2000, 2, 29), date(2026, 2, 28), 25),
        (date(2000, 2, 29), date(2026, 3, 1), 26),
    ],
)
def test_edad_cumplida(nacimiento: date, calculo: date, esperada: int) -> None:
    assert edad_cumplida(nacimiento, calculo) == esperada


@pytest.mark.parametrize(
    ("edad", "tasa"),
    [
        (18, "0.18"),
        (29, "0.18"),
        (30, "0.26"),
        (39, "0.26"),
        (40, "0.45"),
        (49, "0.45"),
        (50, "0.92"),
        (59, "0.92"),
        (60, "1.85"),
        (69, "1.85"),
        (70, "3.40"),
        (75, "3.40"),
    ],
)
def test_tramos_de_edad_incluyen_sus_bordes(edad: int, tasa: str) -> None:
    assert tarifario.tasa_base_mil(edad) == Decimal(tasa)


@pytest.mark.parametrize("edad", [17, 76, 0, 120])
def test_edad_fuera_de_rango_es_rechazada(edad: int) -> None:
    with pytest.raises(ErrorValidacion):
        tarifario.tasa_base_mil(edad)


@pytest.mark.parametrize(
    ("plazo", "factor"),
    [(12, "1.00"), (120, "1.00"), (121, "1.08"), (240, "1.08"), (241, "1.15"), (360, "1.15")],
)
def test_tramos_de_plazo(plazo: int, factor: str) -> None:
    assert tarifario.obtener("2026.02").factor_plazo(plazo) == Decimal(factor)


def test_fumador_encarece_la_prima(solicitud_canonica: SolicitudCotizacion) -> None:
    from dataclasses import replace

    fumador = replace(
        solicitud_canonica,
        asegurado=replace(solicitud_canonica.asegurado, fumador=True),
    )
    base = calcular(solicitud_canonica, FECHA_CALCULO).prima_mensual
    recargada = calcular(fumador, FECHA_CALCULO).prima_mensual

    assert recargada > base


def test_tarifario_anterior_produce_prima_distinta(
    solicitud_canonica: SolicitudCotizacion,
) -> None:
    """Base del modo de fallo `rate_table_stale`: si no divergiera, no serviría."""
    vigente = calcular(solicitud_canonica, FECHA_CALCULO, "2026.02")
    anterior = calcular(solicitud_canonica, FECHA_CALCULO, "2025.11")

    assert vigente.prima_mensual != anterior.prima_mensual


def test_prima_anual_es_doce_veces_la_mensual(
    solicitud_canonica: SolicitudCotizacion,
) -> None:
    resultado = calcular(solicitud_canonica, FECHA_CALCULO)
    assert resultado.prima_anual == resultado.prima_mensual * 12


def test_solicitud_maxima_no_desborda_el_ratio() -> None:
    """La suma máxima con el perfil más caro debe seguir dentro de las cotas."""
    from solventa_common.pricing import validar

    solicitud = SolicitudCotizacion(
        producto=Producto.VIDA_HIPOTECARIO,
        moneda=Moneda.COP,
        suma_asegurada=Decimal("2000000000"),
        plazo_meses=360,
        canal=Canal.RETAIL,
        asegurado=Asegurado(
            fecha_nacimiento=date(1955, 1, 1),
            genero=Genero.M,
            fumador=True,
            clase_ocupacional=4,
        ),
        consentimiento_open_finance=False,
    )
    resultado = calcular(solicitud, FECHA_CALCULO)
    assert validar(resultado, solicitud) == []
