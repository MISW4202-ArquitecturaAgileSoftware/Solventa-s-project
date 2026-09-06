"""Fixtures de Votación: constructores de respuestas sanas y rotas."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from votacion.contracts import (  # noqa: E402
    Asegurado,
    Canal,
    Explicacion,
    Factores,
    Genero,
    Moneda,
    Producto,
    ResultadoCotizacion,
    SolicitudCotizacion,
)

FECHA_CALCULO = date(2026, 8, 31)
VERSION = "2026.02"
CORRELATION_ID = "01a05aa8-24a1-753e-b019-a0810d66a3f6"


@pytest.fixture
def solicitud() -> SolicitudCotizacion:
    return SolicitudCotizacion(
        producto=Producto.VIDA_HIPOTECARIO,
        moneda=Moneda.COP,
        suma_asegurada=Decimal("250000000.00"),
        plazo_meses=240,
        canal=Canal.BANCO_ALIADO,
        asegurado=Asegurado(
            fecha_nacimiento=date(1988, 4, 17),
            genero=Genero.F,
            fumador=False,
            clase_ocupacional=2,
        ),
        consentimiento_open_finance=True,
    )


@pytest.fixture
def sano(solicitud: SolicitudCotizacion) -> ResultadoCotizacion:
    return ResultadoCotizacion(
        moneda=Moneda.COP,
        suma_asegurada=solicitud.suma_asegurada,
        prima_mensual=Decimal("90348.41"),
        prima_anual=Decimal("1084180.92"),
        plazo_meses=solicitud.plazo_meses,
        vigencia_dias=15,
        tarifario_version=VERSION,
        explicacion=Explicacion(
            edad_calculada=38,
            tasa_base_mil=Decimal("0.26"),
            factores=Factores(
                fumador=Decimal("1.00"),
                clase_ocupacional=Decimal("1.12"),
                plazo=Decimal("1.08"),
                canal=Decimal("0.95"),
            ),
            gasto_administrativo=Decimal("0.12"),
            margen=Decimal("0.08"),
        ),
    )
