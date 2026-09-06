"""El denominador de ASR-11 solo cuenta fallos que el modo sí inyecta."""

from datetime import date
from typing import Any

import pytest

from locust_carga.prediccion import es_fallo_efectivo
from locust_carga.solicitudes import solicitud_de

HOY = date(2026, 8, 31)


def _con_clase(clase: int) -> dict[str, Any]:
    solicitud = solicitud_de(0, HOY)
    asegurado = dict(solicitud["asegurado"])
    asegurado["clase_ocupacional"] = clase
    return {**solicitud, "asegurado": asegurado}


@pytest.mark.parametrize(
    ("solicitud", "modo", "efectivo"),
    [
        (_con_clase(1), "factor_skip", False),
        (_con_clase(2), "factor_skip", True),
        (_con_clase(1), "premium_offset", True),
        (_con_clase(1), "none", False),
        (_con_clase(1), "crash", True),
    ],
)
def test_prediccion_por_modo(solicitud: dict[str, Any], modo: str, efectivo: bool) -> None:
    assert es_fallo_efectivo(solicitud, modo, HOY) is efectivo


def test_doce_factor_skip_son_nueve_efectivos() -> None:
    """El ciclo de solicitud_de recorre las 4 clases a partes iguales: 3/12 son clase 1."""
    efectivos = sum(
        es_fallo_efectivo(solicitud_de(indice, HOY), "factor_skip", HOY) for indice in range(12)
    )
    assert efectivos == 9


def test_rate_table_stale_usa_el_oraculo() -> None:
    assert es_fallo_efectivo(solicitud_de(0, HOY), "rate_table_stale", HOY) is True


def test_modo_desconocido_falla_ruidoso() -> None:
    with pytest.raises(ValueError, match="FAULT_MODE desconocido"):
        es_fallo_efectivo(_con_clase(1), "modo_inventado", HOY)
