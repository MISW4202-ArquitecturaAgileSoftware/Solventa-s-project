"""El gateway: identidad del socio, correlación, filtrado y traducción de fallos."""

from typing import Any

import pytest
from flask.testing import FlaskClient

from api_gateway import cliente_votacion as modulo_cliente
from api_gateway.cliente_votacion import RespuestaVotacion, VotacionInalcanzableError

CABECERAS = {"X-Partner-Id": "banco-aliado-01", "content-type": "application/json"}


@pytest.fixture
def votacion_responde(monkeypatch: pytest.MonkeyPatch, respuesta_cotizada: dict[str, Any]):  # type: ignore[no-untyped-def]
    """Sustituye la llamada a Votación. Devuelve las cabeceras que recibió."""
    visto: dict[str, str] = {}

    def _falso(_config: Any, _carga: bytes, *, correlation_id: str, request_id: str):  # type: ignore[no-untyped-def]
        visto["correlation_id"] = correlation_id
        visto["request_id"] = request_id
        return RespuestaVotacion(200, respuesta_cotizada)

    monkeypatch.setattr(modulo_cliente, "cotizar", _falso)
    return visto


# --- Identidad del socio -----------------------------------------------------


def test_sin_partner_id_devuelve_401(cliente: FlaskClient, solicitud: dict[str, Any]) -> None:
    respuesta = cliente.post(
        "/v1/cotizaciones", json=solicitud, headers={"content-type": "application/json"}
    )

    assert respuesta.status_code == 401
    assert respuesta.mimetype == "application/problem+json"
    assert respuesta.get_json()["type"].endswith("/socio-no-identificado")


def test_partner_id_en_blanco_devuelve_401(cliente: FlaskClient, solicitud: dict[str, Any]) -> None:
    respuesta = cliente.post(
        "/v1/cotizaciones", json=solicitud, headers={**CABECERAS, "X-Partner-Id": "   "}
    )
    assert respuesta.status_code == 401


# --- Correlación -------------------------------------------------------------


def test_toda_respuesta_lleva_correlation_id(
    cliente: FlaskClient, solicitud: dict[str, Any], votacion_responde: dict[str, str]
) -> None:
    respuesta = cliente.post("/v1/cotizaciones", json=solicitud, headers=CABECERAS)
    assert respuesta.headers["X-Correlation-Id"]


def test_las_respuestas_de_error_tambien_lo_llevan(
    cliente: FlaskClient, solicitud: dict[str, Any]
) -> None:
    """Son justo las que más falta hace poder rastrear."""
    respuesta = cliente.post(
        "/v1/cotizaciones", json=solicitud, headers={"content-type": "application/json"}
    )

    assert respuesta.status_code == 401
    assert respuesta.headers["X-Correlation-Id"] != "-"


def test_el_gateway_genera_el_correlation_id(
    cliente: FlaskClient, solicitud: dict[str, Any], votacion_responde: dict[str, str]
) -> None:
    """Es el único punto de entrada: ningún tramo interno debe inventarse uno."""
    import uuid

    cliente.post("/v1/cotizaciones", json=solicitud, headers=CABECERAS)
    assert uuid.UUID(votacion_responde["correlation_id"]).version == 7


def test_se_conserva_el_request_id_del_socio(
    cliente: FlaskClient, solicitud: dict[str, Any], votacion_responde: dict[str, str]
) -> None:
    cliente.post(
        "/v1/cotizaciones",
        json=solicitud,
        headers={**CABECERAS, "X-Request-Id": "ref-del-socio-123"},
    )

    assert votacion_responde["request_id"] == "ref-del-socio-123"
    assert votacion_responde["correlation_id"] != "ref-del-socio-123"


def test_sin_request_id_se_usa_el_correlation_id(
    cliente: FlaskClient, solicitud: dict[str, Any], votacion_responde: dict[str, str]
) -> None:
    cliente.post("/v1/cotizaciones", json=solicitud, headers=CABECERAS)
    assert votacion_responde["request_id"] == votacion_responde["correlation_id"]


def test_dos_peticiones_no_comparten_correlation_id(
    cliente: FlaskClient, solicitud: dict[str, Any], votacion_responde: dict[str, str]
) -> None:
    """El hilo de gunicorn se reutiliza: sin limpiar el contexto, la segunda
    petición heredaría el identificador de la primera."""
    primera = cliente.post("/v1/cotizaciones", json=solicitud, headers=CABECERAS)
    segunda = cliente.post("/v1/cotizaciones", json=solicitud, headers=CABECERAS)

    assert primera.headers["X-Correlation-Id"] != segunda.headers["X-Correlation-Id"]


# --- Filtrado del bloque de consenso (ASR-12) --------------------------------


def test_el_socio_no_ve_el_consenso(
    cliente: FlaskClient, solicitud: dict[str, Any], votacion_responde: dict[str, str]
) -> None:
    """ASR-12 exige responder «sin exponer el error», aunque Votación lo envíe."""
    cuerpo = cliente.post("/v1/cotizaciones", json=solicitud, headers=CABECERAS).get_json()

    assert "consenso" not in cuerpo
    assert cuerpo["cotizacion"]["prima_mensual"] == "90348.41"


def test_con_el_flag_activo_el_consenso_se_expone(
    app: Any, cliente: FlaskClient, solicitud: dict[str, Any], votacion_responde: Any
) -> None:
    from dataclasses import replace

    app.config["SOLVENTA"] = replace(app.config["SOLVENTA"], expose_consensus=True)
    cuerpo = cliente.post("/v1/cotizaciones", json=solicitud, headers=CABECERAS).get_json()

    assert cuerpo["consenso"]["replicas_divergentes"] == ["B"]


# --- Traducción de fallos de Votación ---------------------------------------


def test_los_errores_de_votacion_se_propagan(
    monkeypatch: pytest.MonkeyPatch, cliente: FlaskClient, solicitud: dict[str, Any]
) -> None:
    """El 422 de Votación ya nombra el campo ofensor: reescribirlo lo empeoraría."""
    problema = {
        "type": "https://solventa.co/errors/validacion",
        "title": "Solicitud de cotización inválida",
        "status": 422,
        "detail": "asegurado.clase_ocupacional debe estar entre 1 y 4",
    }
    monkeypatch.setattr(
        modulo_cliente,
        "cotizar",
        lambda *a, **k: RespuestaVotacion(422, problema),
    )

    respuesta = cliente.post("/v1/cotizaciones", json=solicitud, headers=CABECERAS)

    assert respuesta.status_code == 422
    assert "clase_ocupacional" in respuesta.get_json()["detail"]


def test_votacion_inalcanzable_no_filtra_la_topologia(
    monkeypatch: pytest.MonkeyPatch, cliente: FlaskClient, solicitud: dict[str, Any]
) -> None:
    """El socio no debe enterarse de qué componente interno falló."""

    def _cae(*_a: Any, **_k: Any) -> None:
        raise VotacionInalcanzableError("<urlopen error [Errno 111] a votacion:8000>")

    monkeypatch.setattr(modulo_cliente, "cotizar", _cae)
    cuerpo = cliente.post("/v1/cotizaciones", json=solicitud, headers=CABECERAS).get_json()

    texto = str(cuerpo)
    assert cuerpo["status"] == 503
    assert "votacion" not in texto
    assert "Errno" not in texto


# --- Limitación de tasa ------------------------------------------------------


def test_se_limita_por_socio(
    cliente: FlaskClient, solicitud: dict[str, Any], votacion_responde: dict[str, str]
) -> None:
    for _ in range(5):  # el límite de la fixture
        assert (
            cliente.post("/v1/cotizaciones", json=solicitud, headers=CABECERAS).status_code == 200
        )

    excedida = cliente.post("/v1/cotizaciones", json=solicitud, headers=CABECERAS)

    assert excedida.status_code == 429
    assert excedida.headers["Retry-After"]
    assert excedida.mimetype == "application/problem+json"


def test_el_limite_de_un_socio_no_afecta_a_otro(
    cliente: FlaskClient, solicitud: dict[str, Any], votacion_responde: dict[str, str]
) -> None:
    for _ in range(5):
        cliente.post("/v1/cotizaciones", json=solicitud, headers=CABECERAS)

    otro = cliente.post(
        "/v1/cotizaciones",
        json=solicitud,
        headers={**CABECERAS, "X-Partner-Id": "retail-02"},
    )
    assert otro.status_code == 200


# --- Salud -------------------------------------------------------------------


def test_health_no_exige_socio(cliente: FlaskClient) -> None:
    assert cliente.get("/health").status_code == 200


def test_ruta_inexistente(cliente: FlaskClient) -> None:
    assert cliente.get("/v1/nada").status_code == 404


def test_el_gateway_sella_su_correlation_id_en_los_errores_propagados(
    monkeypatch: pytest.MonkeyPatch, cliente: FlaskClient, solicitud: dict[str, Any]
) -> None:
    """El socio solo conoce el identificador que le devolvió el borde."""
    problema = {
        "type": "https://solventa.co/errors/validacion",
        "title": "Solicitud de cotización inválida",
        "status": 422,
        "detail": "moneda es obligatorio",
        "instance": "/v1/cotizaciones",
        "correlation_id": "-",
    }
    monkeypatch.setattr(modulo_cliente, "cotizar", lambda *a, **k: RespuestaVotacion(422, problema))

    respuesta = cliente.post("/v1/cotizaciones", json=solicitud, headers=CABECERAS)
    cuerpo = respuesta.get_json()

    assert cuerpo["correlation_id"] == respuesta.headers["X-Correlation-Id"]
    assert cuerpo["correlation_id"] != "-"
