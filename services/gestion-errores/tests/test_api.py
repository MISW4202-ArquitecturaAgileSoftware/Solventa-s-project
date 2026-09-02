"""Endpoints del registro de incidentes."""

import json
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from gestion_errores.config import Config


def _reportar(cliente: FlaskClient, incidente: dict[str, Any]) -> Any:
    return cliente.post("/v1/incidentes", json=incidente)


def test_reportar_confirma_la_creacion(cliente: FlaskClient, incidente: dict[str, Any]) -> None:
    respuesta = _reportar(cliente, incidente)

    assert respuesta.status_code == 201
    assert respuesta.get_json()["creado"] is True


def test_el_incidente_acaba_en_el_jsonl(
    cliente: FlaskClient,
    incidente: dict[str, Any],
    config: Config,
) -> None:
    _reportar(cliente, incidente)

    lineas = config.ruta_incidentes.read_text(encoding="utf-8").strip().splitlines()
    assert len(lineas) == 1
    guardado = json.loads(lineas[0])
    assert guardado["correlation_id"] == incidente["correlation_id"]
    assert guardado["replicas_divergentes"] == ["B"]
    assert guardado["valores_recibidos"][1]["resultado"]["prima_mensual"] == "103900.67"


def test_metricas_cuentan_por_tipo(cliente: FlaskClient, incidente: dict[str, Any]) -> None:
    """Numerador de ASR-11."""
    _reportar(cliente, incidente)

    cuerpo = cliente.get("/v1/metricas").get_json()

    assert cuerpo["total"] == 1
    assert cuerpo["por_tipo"]["divergencia_resultado"] == 1
    assert cuerpo["por_replica_divergente"]["B"] == 1


def test_consulta_por_correlation_id(
    cliente: FlaskClient, incidente: dict[str, Any]
) -> None:
    otro = incidente | {"correlation_id": "01a05aa8-0000-7000-8000-000000000000"}
    _reportar(cliente, incidente)
    _reportar(cliente, otro)

    cuerpo = cliente.get(f"/v1/incidentes?correlation_id={incidente['correlation_id']}").get_json()

    assert cuerpo["total"] == 1
    assert cuerpo["incidentes"][0]["correlation_id"] == incidente["correlation_id"]


def test_consulta_sin_incidentes(cliente: FlaskClient) -> None:
    cuerpo = cliente.get("/v1/incidentes?correlation_id=inexistente").get_json()
    assert cuerpo == {"total": 0, "incidentes": []}


@pytest.mark.parametrize(
    ("parche", "descripcion"),
    [
        ({"tipo": "tipo_inventado"}, "tipo fuera del enum"),
        ({"correlation_id": 123}, "correlation_id no textual"),
        ({"detectado_en": "ayer"}, "fecha no ISO"),
        ({"replicas_divergentes": "B"}, "replicas no es lista"),
    ],
)
def test_incidente_invalido_es_rechazado(
    cliente: FlaskClient, incidente: dict[str, Any], parche: dict[str, Any], descripcion: str
) -> None:
    respuesta = _reportar(cliente, incidente | parche)

    assert respuesta.status_code == 422, descripcion
    assert respuesta.mimetype == "application/problem+json"


def test_cuerpo_no_json_es_rechazado(cliente: FlaskClient) -> None:
    respuesta = cliente.post("/v1/incidentes", data="no soy json", content_type="text/plain")
    assert respuesta.status_code == 422


def test_los_tres_tipos_de_incidente_se_aceptan(
    cliente: FlaskClient, incidente: dict[str, Any]
) -> None:
    tipos = ["divergencia_resultado", "sin_quorum", "replica_no_responde"]
    for tipo in tipos:
        assert _reportar(cliente, incidente | {"tipo": tipo}).status_code == 201

    por_tipo = cliente.get("/v1/metricas").get_json()["por_tipo"]
    assert set(por_tipo) == set(tipos)


def test_ruta_inexistente(cliente: FlaskClient) -> None:
    assert cliente.get("/v1/nada").status_code == 404


def test_una_linea_ilegible_no_invalida_el_historico(
    cliente: FlaskClient,
    incidente: dict[str, Any],
    config: Config,
) -> None:
    """Un corte a mitad de escritura no puede impedir leer lo demás."""
    _reportar(cliente, incidente)
    with Path(config.ruta_incidentes).open("a", encoding="utf-8") as f:
        f.write('{"truncado": \n')

    assert cliente.get("/v1/metricas").get_json()["total"] == 1
