"""Endpoints del registro de incidentes."""

import json
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from gestion_errores.config import Config


def _reportar(cliente: FlaskClient, incidente: dict[str, Any]) -> Any:
    return cliente.post("/v1/incidentes", json=incidente)


def test_reportar_devuelve_202(cliente: FlaskClient, incidente: dict[str, Any]) -> None:
    """202 y no 201: al responder, el incidente está aceptado pero puede no
    estar aún en disco. Decir Created sería mentir sobre la escritura."""
    respuesta = _reportar(cliente, incidente)

    assert respuesta.status_code == 202
    assert respuesta.get_json()["aceptado"] is True


def test_el_incidente_acaba_en_el_jsonl(
    cliente: FlaskClient,
    incidente: dict[str, Any],
    config: Config,
    esperar_escritura: Any,
) -> None:
    _reportar(cliente, incidente)
    esperar_escritura()

    lineas = config.ruta_incidentes.read_text(encoding="utf-8").strip().splitlines()
    assert len(lineas) == 1
    guardado = json.loads(lineas[0])
    assert guardado["correlation_id"] == incidente["correlation_id"]
    assert guardado["replicas_divergentes"] == ["B"]
    assert guardado["valor_consenso"] == "90348.41"


def test_metricas_cuentan_por_tipo(
    cliente: FlaskClient, incidente: dict[str, Any], esperar_escritura: Any
) -> None:
    """Numerador de ASR-11."""
    _reportar(cliente, incidente)
    esperar_escritura()

    cuerpo = cliente.get("/v1/metricas").get_json()

    assert cuerpo["total"] == 1
    assert cuerpo["por_tipo"]["divergencia_resultado"] == 1
    assert cuerpo["por_replica_divergente"]["B"] == 1
    assert cuerpo["pendientes_de_escritura"] == 0


def test_metricas_exponen_lo_pendiente(cliente: FlaskClient) -> None:
    """Quien mide necesita saber si la cuenta está completa, no adivinarlo."""
    assert "pendientes_de_escritura" in cliente.get("/v1/metricas").get_json()


def test_consulta_por_correlation_id(
    cliente: FlaskClient, incidente: dict[str, Any], esperar_escritura: Any
) -> None:
    otro = incidente | {"correlation_id": "01a05aa8-0000-7000-8000-000000000000"}
    _reportar(cliente, incidente)
    _reportar(cliente, otro)
    esperar_escritura()

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


def test_los_cuatro_tipos_de_incidente_se_aceptan(
    cliente: FlaskClient, incidente: dict[str, Any], esperar_escritura: Any
) -> None:
    tipos = ["divergencia_resultado", "regla_de_validez", "sin_quorum", "replica_no_responde"]
    for tipo in tipos:
        assert _reportar(cliente, incidente | {"tipo": tipo}).status_code == 202
    esperar_escritura()

    por_tipo = cliente.get("/v1/metricas").get_json()["por_tipo"]
    assert set(por_tipo) == set(tipos)


def test_health_y_ready(cliente: FlaskClient) -> None:
    assert cliente.get("/health").status_code == 200
    assert cliente.get("/ready").status_code == 200
    assert cliente.get("/ready").get_json()["escritor_vivo"] is True


def test_ruta_inexistente(cliente: FlaskClient) -> None:
    assert cliente.get("/v1/nada").status_code == 404


def test_una_linea_ilegible_no_invalida_el_historico(
    cliente: FlaskClient,
    incidente: dict[str, Any],
    config: Config,
    esperar_escritura: Any,
) -> None:
    """Un corte a mitad de escritura no puede impedir leer lo demás."""
    _reportar(cliente, incidente)
    esperar_escritura()
    with Path(config.ruta_incidentes).open("a", encoding="utf-8") as f:
        f.write('{"truncado": \n')

    assert cliente.get("/v1/metricas").get_json()["total"] == 1
