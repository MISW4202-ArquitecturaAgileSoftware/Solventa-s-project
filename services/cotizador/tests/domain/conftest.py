"""Fixtures compartidas: el ejemplo canónico del plan (§2.3)."""

from datetime import date
from decimal import Decimal

import pytest

from cotizador.common.contracts import (
    Asegurado,
    Canal,
    Genero,
    Moneda,
    Producto,
    SolicitudCotizacion,
)

# Fecha de cálculo fija. Congelarla es lo que hace reproducible el test: la edad
# del ejemplo canónico (38) depende de ella.
FECHA_CALCULO = date(2026, 8, 31)


@pytest.fixture
def solicitud_canonica() -> SolicitudCotizacion:
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
