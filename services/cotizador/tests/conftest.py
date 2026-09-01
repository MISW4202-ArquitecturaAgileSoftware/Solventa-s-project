"""Hace importable `cotizador` en los tests locales.

El servicio no se instala como paquete —la decisión de layout fue
`requirements.txt` por servicio, sin workspace—, así que su `src/` se añade al
path. Dentro de la imagen no hace falta: el Dockerfile fija `PYTHONPATH`.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from solventa_common.contracts import (  # noqa: E402
    Asegurado,
    Canal,
    Genero,
    Moneda,
    Producto,
    SolicitudCotizacion,
)
from solventa_common.pricing import calcular  # noqa: E402

FECHA_CALCULO = date(2026, 8, 31)
VERSION = "2026.02"


@pytest.fixture
def solicitud() -> SolicitudCotizacion:
    from decimal import Decimal

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
def resultado_sano(solicitud: SolicitudCotizacion):  # type: ignore[no-untyped-def]
    return calcular(solicitud, FECHA_CALCULO, VERSION)
