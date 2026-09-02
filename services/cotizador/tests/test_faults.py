"""Cada modo de fallo altera la prima como especifica el experimento."""

import time
from datetime import date
from decimal import Decimal

import pytest

from cotizador import faults
from cotizador.contracts import ResultadoCotizacion, SolicitudCotizacion

# Declarados aquí y no importados de conftest: añadir __init__.py a este
# directorio crearía un segundo paquete llamado `tests` y chocaría con el de
# otros paquetes al recorrer todo el monorepo.
FECHA_CALCULO = date(2026, 8, 31)
VERSION = "2026.02"


def _calcular(solicitud: SolicitudCotizacion, modo: str) -> ResultadoCotizacion:
    return faults.calcular(solicitud, FECHA_CALCULO, VERSION, modo)


# --- Importes esperados, modo a modo ----------------------------------------


@pytest.mark.parametrize(
    ("modo", "prima"),
    [
        ("none", "90348.41"),
        ("premium_offset", "103900.67"),
        ("factor_skip", "80668.22"),
        ("rate_table_stale", "82653.90"),
        ("rounding_drift", "90348.00"),
        ("out_of_range", "45174205.00"),
        ("silent_zero", "0.00"),
        ("slow", "90348.41"),
    ],
)
def test_prima_por_modo(solicitud: SolicitudCotizacion, modo: str, prima: str) -> None:
    assert _calcular(solicitud, modo).prima_mensual == Decimal(prima)


def test_sin_fallo_coincide_con_el_dominio(
    solicitud: SolicitudCotizacion, resultado_sano: ResultadoCotizacion
) -> None:
    assert _calcular(solicitud, "none") == resultado_sano


def test_crash_no_produce_resultado(solicitud: SolicitudCotizacion) -> None:
    with pytest.raises(faults.FalloInyectado):
        _calcular(solicitud, "crash")


def test_modo_desconocido_falla_al_arrancar(solicitud: SolicitudCotizacion) -> None:
    """Mejor un error ruidoso que una réplica silenciosamente sana."""
    with pytest.raises(RuntimeError, match="FAULT_MODE desconocido"):
        _calcular(solicitud, "modo_inventado")


def test_slow_retrasa_pero_no_corrompe(
    solicitud: SolicitudCotizacion, resultado_sano: ResultadoCotizacion
) -> None:
    inicio = time.perf_counter()
    resultado = _calcular(solicitud, "slow")
    transcurrido = time.perf_counter() - inicio

    assert resultado == resultado_sano
    # Debe exceder el presupuesto de 250 ms de Votación para forzar quórum parcial.
    assert transcurrido >= 0.4


@pytest.mark.parametrize(
    "modo",
    [m.value for m in faults.ModoFallo if m.value not in {"none", "slow", "crash"}],
)
def test_todo_fallo_que_produce_resultado_cambia_la_prima(
    solicitud: SolicitudCotizacion, resultado_sano: ResultadoCotizacion, modo: str
) -> None:
    assert _calcular(solicitud, modo).prima_mensual != resultado_sano.prima_mensual


def test_los_modos_temporales_no_alteran_el_resultado(
    solicitud: SolicitudCotizacion, resultado_sano: ResultadoCotizacion
) -> None:
    """`slow` retrasa y `crash` calla, pero ninguno miente sobre el importe."""
    assert _calcular(solicitud, "slow") == resultado_sano


def test_la_prima_desviada_conserva_la_coherencia_anual(
    solicitud: SolicitudCotizacion,
) -> None:
    """Si la anual quedara descuadrada, `coherencia_anual` delataría el fallo
    por sí sola y `premium_offset` dejaría de probar la vía de divergencia."""
    from cotizador.pricing import redondear

    roto = _calcular(solicitud, "premium_offset")
    assert roto.prima_anual == redondear(roto.prima_mensual * 12)
