"""Pruebas del único comportamiento del gateway: recibir y reenviar."""

import logging
import sys
from pathlib import Path
from typing import Any

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api_gateway import app as gateway  # noqa: E402


class RespuestaFalsa:
    def __init__(self, estado: int = 200, cuerpo: Any = None) -> None:
        self.status_code = estado
        self._cuerpo = cuerpo if cuerpo is not None else {"estado": "COTIZADO"}

    def json(self) -> Any:
        if isinstance(self._cuerpo, ValueError):
            raise self._cuerpo
        return self._cuerpo


@pytest.fixture
def cliente():  # type: ignore[no-untyped-def]
    gateway.app.config["TESTING"] = True
    return gateway.app.test_client()


@pytest.fixture
def solicitud() -> dict[str, Any]:
    return {
        "request_id": "solicitud-001",
        "producto": "vida_hipotecario",
        "suma_asegurada": "250000000.00",
    }


def test_rechaza_json_invalido(cliente: Any) -> None:
    respuesta = cliente.post("/v1/cotizaciones", data="no-json")
    assert respuesta.status_code == 400
    assert respuesta.get_json() == {"error": "invalid_json"}


def test_request_id_es_obligatorio(cliente: Any) -> None:
    respuesta = cliente.post("/v1/cotizaciones", json={"producto": "vida"})
    assert respuesta.status_code == 400
    assert respuesta.get_json() == {"error": "request_id_required"}


def test_reenvia_cuerpo_identificadores_y_timeout(
    monkeypatch: pytest.MonkeyPatch, cliente: Any, solicitud: dict[str, Any]
) -> None:
    visto: dict[str, Any] = {}

    def post(url: str, **argumentos: Any) -> RespuestaFalsa:
        visto.update(url=url, **argumentos)
        return RespuestaFalsa(cuerpo={"estado": "COTIZADO"})

    monkeypatch.setattr(gateway.requests, "post", post)
    respuesta = cliente.post("/v1/cotizaciones", json=solicitud)

    assert respuesta.status_code == 200
    assert visto["url"] == gateway.QUOTATION_SERVICE_URL
    assert visto["json"] == solicitud
    assert visto["headers"]["X-Request-Id"] == "solicitud-001"
    assert visto["headers"]["X-Correlation-Id"] == respuesta.headers["X-Correlation-Id"]
    assert visto["timeout"] == gateway.UPSTREAM_TIMEOUT_MS / 1000


def test_propaga_estado_y_cuerpo_del_servicio(
    monkeypatch: pytest.MonkeyPatch, cliente: Any, solicitud: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        gateway.requests,
        "post",
        lambda *a, **k: RespuestaFalsa(422, {"error": "dato_invalido"}),
    )
    respuesta = cliente.post("/v1/cotizaciones", json=solicitud)
    assert respuesta.status_code == 422
    assert respuesta.get_json() == {"error": "dato_invalido"}


def test_timeout_devuelve_504(
    monkeypatch: pytest.MonkeyPatch, cliente: Any, solicitud: dict[str, Any]
) -> None:
    def timeout(*_a: Any, **_k: Any) -> None:
        raise gateway.requests.Timeout()

    monkeypatch.setattr(gateway.requests, "post", timeout)
    respuesta = cliente.post("/v1/cotizaciones", json=solicitud)
    assert respuesta.status_code == 504
    assert respuesta.get_json() == {"error": "upstream_timeout"}


def test_conexion_fallida_devuelve_503(
    monkeypatch: pytest.MonkeyPatch, cliente: Any, solicitud: dict[str, Any]
) -> None:
    def falla(*_a: Any, **_k: Any) -> None:
        raise gateway.requests.ConnectionError()

    monkeypatch.setattr(gateway.requests, "post", falla)
    respuesta = cliente.post("/v1/cotizaciones", json=solicitud)
    assert respuesta.status_code == 503
    assert respuesta.get_json() == {"error": "upstream_unavailable"}


def test_respuesta_no_json_devuelve_502(
    monkeypatch: pytest.MonkeyPatch, cliente: Any, solicitud: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        gateway.requests,
        "post",
        lambda *a, **k: RespuestaFalsa(cuerpo=ValueError("no es JSON")),
    )
    respuesta = cliente.post("/v1/cotizaciones", json=solicitud)
    assert respuesta.status_code == 502
    assert respuesta.get_json() == {"error": "invalid_upstream_response"}


@pytest.mark.parametrize(
    ("resultado", "nivel_esperado"),
    [
        (RespuestaFalsa(), logging.INFO),
        (gateway.requests.Timeout(), logging.WARNING),
        (gateway.requests.ConnectionError(), logging.ERROR),
        (RespuestaFalsa(cuerpo=ValueError("no es JSON")), logging.WARNING),
    ],
)
def test_el_log_usa_el_nivel_adecuado(
    monkeypatch: pytest.MonkeyPatch,
    cliente: Any,
    solicitud: dict[str, Any],
    resultado: Any,
    nivel_esperado: int,
) -> None:
    niveles: list[int] = []

    def post(*_a: Any, **_k: Any) -> RespuestaFalsa:
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    monkeypatch.setattr(gateway.requests, "post", post)
    monkeypatch.setattr(
        gateway,
        "registrar_log",
        lambda nivel, *_a, **_k: niveles.append(nivel),
    )

    cliente.post("/v1/cotizaciones", json=solicitud)

    assert niveles == [nivel_esperado]
