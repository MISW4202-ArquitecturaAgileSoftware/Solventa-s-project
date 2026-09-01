"""Determinismo: la propiedad de la que depende toda la votación."""

from dataclasses import replace
from decimal import Decimal

from solventa_common.contracts import SolicitudCotizacion
from solventa_common.hashing import cuerpo_hashable, json_canonico, resultado_hash
from solventa_common.pricing import calcular

from .conftest import FECHA_CALCULO


def test_mil_ejecuciones_producen_el_mismo_hash(
    solicitud_canonica: SolicitudCotizacion,
) -> None:
    """Si esto falla, hay una entrada implícita en el cálculo (reloj, orden de
    diccionario, float) y la votación reportaría divergencias falsas."""
    hashes = {resultado_hash(calcular(solicitud_canonica, FECHA_CALCULO)) for _ in range(1000)}
    assert len(hashes) == 1


def test_json_canonico_ordena_claves() -> None:
    assert json_canonico({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_json_canonico_sin_espacios() -> None:
    assert " " not in json_canonico({"a": 1, "b": {"c": 2}})


def test_prima_distinta_cambia_el_hash(
    solicitud_canonica: SolicitudCotizacion,
) -> None:
    sano = calcular(solicitud_canonica, FECHA_CALCULO)
    desviado = replace(sano, prima_mensual=sano.prima_mensual + Decimal("0.01"))

    assert resultado_hash(sano) != resultado_hash(desviado)


def test_el_hash_ignora_lo_que_varia_por_replica(
    solicitud_canonica: SolicitudCotizacion,
) -> None:
    """cotizador_id y duracion_ms no forman parte del resultado a comparar."""
    cuerpo = cuerpo_hashable(calcular(solicitud_canonica, FECHA_CALCULO))

    assert set(cuerpo) == {
        "prima_mensual",
        "prima_anual",
        "tasa_base_mil",
        "factores",
        "tarifario_version",
        "edad_calculada",
    }


def test_tarifario_distinto_cambia_el_hash(
    solicitud_canonica: SolicitudCotizacion,
) -> None:
    vigente = calcular(solicitud_canonica, FECHA_CALCULO, "2026.02")
    anterior = calcular(solicitud_canonica, FECHA_CALCULO, "2025.11")

    assert resultado_hash(vigente) != resultado_hash(anterior)
