"""Fixtures de Votación: constructores de respuestas sanas y rotas."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from votacion.common.contracts import (  # noqa: E402
    Asegurado,
    Canal,
    Genero,
    Moneda,
    Producto,
    ResultadoCotizacion,
    SolicitudCotizacion,
)
from votacion.common.pricing import calcular  # noqa: E402

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
    return calcular(solicitud, FECHA_CALCULO, VERSION)
