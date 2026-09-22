"""Tests de `ClienteHttpReal`: traducción de los fallos de `requests` a
`ErrorUpstream` (PLAN-IMPLEMENTACION.md §3.1)."""

from typing import Any, ClassVar

import pytest
import requests  # type: ignore[import-untyped]

from api_gateway.errors import ErrorUpstream
from api_gateway.http import ClienteHttpReal


class _RespuestaSinJson:
    status_code = 200
    headers: ClassVar[dict[str, str]] = {}

    def json(self) -> Any:
        raise ValueError("no es JSON")


def test_timeout_se_traduce_a_upstream_504(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = ClienteHttpReal(timeout_s=1.0)

    def _falla(*_args: object, **_kwargs: object) -> Any:
        raise requests.Timeout("lento")

    monkeypatch.setattr(cliente._sesion, "post", _falla)

    with pytest.raises(ErrorUpstream) as exc:
        cliente.post("http://interno.test/x", {"a": 1}, "cid-1")
    assert exc.value.estado == 504


def test_conexion_rechazada_se_traduce_a_upstream_503(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = ClienteHttpReal(timeout_s=1.0)

    def _falla(*_args: object, **_kwargs: object) -> Any:
        raise requests.ConnectionError("rechazada")

    monkeypatch.setattr(cliente._sesion, "post", _falla)

    with pytest.raises(ErrorUpstream) as exc:
        cliente.post("http://interno.test/x", {"a": 1}, "cid-1")
    assert exc.value.estado == 503


def test_otro_fallo_de_requests_se_traduce_a_upstream_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = ClienteHttpReal(timeout_s=1.0)

    def _falla(*_args: object, **_kwargs: object) -> Any:
        raise requests.exceptions.TooManyRedirects("demasiadas redirecciones")

    monkeypatch.setattr(cliente._sesion, "post", _falla)

    with pytest.raises(ErrorUpstream) as exc:
        cliente.post("http://interno.test/x", {"a": 1}, "cid-1")
    assert exc.value.estado == 502


def test_cuerpo_no_json_se_traduce_a_upstream_502(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = ClienteHttpReal(timeout_s=1.0)

    monkeypatch.setattr(cliente._sesion, "post", lambda *a, **k: _RespuestaSinJson())

    with pytest.raises(ErrorUpstream) as exc:
        cliente.post("http://interno.test/x", {"a": 1}, "cid-1")
    assert exc.value.estado == 502


def test_respuesta_correcta_conserva_estado_cuerpo_y_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RespuestaOk:
        status_code = 202
        headers: ClassVar[dict[str, str]] = {"Content-Type": "application/problem+json"}

        def json(self) -> Any:
            return {"estado": "OTP_REQUERIDO"}

    cliente = ClienteHttpReal(timeout_s=1.0)
    monkeypatch.setattr(cliente._sesion, "post", lambda *a, **k: _RespuestaOk())

    respuesta = cliente.post("http://interno.test/x", {"a": 1}, "cid-1")

    assert respuesta.estado == 202
    assert respuesta.cuerpo == {"estado": "OTP_REQUERIDO"}
    assert respuesta.content_type == "application/problem+json"
