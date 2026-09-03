"""Identificación de peticiones y traducción de errores a RFC 9457."""

import uuid

import pytest

from cotizador.common.errors import (
    ErrorSinConsenso,
    ErrorSocioNoIdentificado,
    ErrorSolventa,
    ErrorTimeoutCotizacion,
    ErrorValidacion,
    a_problem_json,
)
from cotizador.common.ids import es_correlation_id_valido, nuevo_correlation_id


def test_correlation_id_es_uuid_version_7() -> None:
    assert uuid.UUID(nuevo_correlation_id()).version == 7


def test_correlation_ids_no_se_repiten() -> None:
    assert len({nuevo_correlation_id() for _ in range(10_000)}) == 10_000


def test_correlation_ids_son_ordenados_en_el_tiempo() -> None:
    """La razón de elegir v7 sobre v4: ordenan solos en logs y en el stream."""
    generados = [nuevo_correlation_id() for _ in range(200)]
    assert generados == sorted(generados)


@pytest.mark.parametrize("valor", ["", "no-es-uuid", "123", "01a05aa8-24a1"])
def test_correlation_id_invalido(valor: str) -> None:
    assert not es_correlation_id_valido(valor)


def test_se_acepta_un_uuid_v4_del_socio() -> None:
    """El socio puede traer su propio identificador; no exigimos versión 7."""
    assert es_correlation_id_valido(str(uuid.uuid4()))


@pytest.mark.parametrize(
    ("error", "estado"),
    [
        (ErrorValidacion("plazo_meses", "debe estar entre 12 y 360"), 422),
        (ErrorSocioNoIdentificado("falta X-Partner-Id"), 401),
        (ErrorSinConsenso("ninguna réplica superó las reglas de validez"), 503),
        (ErrorTimeoutCotizacion("venció el presupuesto de 250 ms"), 504),
    ],
)
def test_traduccion_a_problem_json(error: ErrorSolventa, estado: int) -> None:
    cuerpo, codigo = a_problem_json(error, instance="/v1/cotizaciones", correlation_id="01a05aa8")

    assert codigo == estado
    assert cuerpo["status"] == estado
    assert cuerpo["type"].startswith("https://solventa.co/errors/")
    assert cuerpo["instance"] == "/v1/cotizaciones"
    assert cuerpo["correlation_id"] == "01a05aa8"
    assert cuerpo["detail"]


def test_el_error_de_validacion_nombra_el_campo_ofensor() -> None:
    cuerpo, _ = a_problem_json(
        ErrorValidacion("asegurado.clase_ocupacional", "debe estar entre 1 y 4"),
        instance="/v1/cotizaciones",
        correlation_id="01a05aa8",
    )
    assert "asegurado.clase_ocupacional" in cuerpo["detail"]


def test_el_titulo_puede_ajustarse_al_recurso() -> None:
    """El mismo ErrorValidacion titula distinto según qué recurso lo produjo."""
    cuerpo, _ = a_problem_json(
        ErrorValidacion("tipo", "fuera del enum"),
        instance="/v1/incidentes",
        correlation_id="01a05aa8",
        titulo="Incidente inválido",
    )
    assert cuerpo["title"] == "Incidente inválido"
    assert cuerpo["type"].endswith("/validacion")
