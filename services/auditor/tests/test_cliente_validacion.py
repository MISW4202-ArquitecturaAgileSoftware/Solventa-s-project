import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from auditor.cliente_validacion import ClienteValidacion, ErrorValidacionTransitoria
from auditor.config import Config
from auditor.contracts import Accion, Actor, Decision, EventoAuditoria, Recurso, Rol, ahora_utc


def _evento(region: str | None = "sur") -> EventoAuditoria:
    return EventoAuditoria(
        evento_id="019a",
        correlation_id="019b",
        tipo="operacion.auditada",
        version="1",
        emitido_en=ahora_utc(),
        actor=Actor(employee_id="E-ASN-01", session_id="019c", rol=Rol.ASESOR),
        accion=Accion.CONSULTA_POLIZA,
        recurso=Recurso(
            tipo="poliza", poliza_id="POL-SUR-003", region=region, cliente_id="CLI-SUR-003"
        ),
        resultado="OK",
    )


class _RespuestaFalsa:
    def __init__(self, status: int, cuerpo: dict[str, Any]) -> None:
        self.status = status
        self._cuerpo = json.dumps(cuerpo).encode("utf-8")

    def read(self) -> bytes:
        return self._cuerpo

    def __enter__(self) -> _RespuestaFalsa:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_informar_anomalia_envia_el_cuerpo_exacto_de_3_4(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    capturado: dict[str, Any] = {}

    def urlopen_falso(
        peticion: urllib.request.Request, timeout: float | None = None
    ) -> _RespuestaFalsa:
        datos = peticion.data
        assert isinstance(datos, bytes)
        capturado["url"] = peticion.full_url
        capturado["cuerpo"] = json.loads(datos)
        capturado["correlation_id"] = peticion.get_header("X-correlation-id")
        return _RespuestaFalsa(202, {"evento_id": "019a", "decision": "ALERTAR"})

    monkeypatch.setattr(urllib.request, "urlopen", urlopen_falso)
    cliente = ClienteValidacion(config)

    decision = cliente.informar_anomalia(_evento(region="sur"))

    assert decision == Decision.ALERTAR
    assert capturado["url"] == "http://validacion:8000/v1/anomalias"
    assert capturado["correlation_id"] == "019b"
    assert capturado["cuerpo"] == {
        "evento_id": "019a",
        "correlation_id": "019b",
        "employee_id": "E-ASN-01",
        "session_id": "019c",
        "accion": "CONSULTA_POLIZA",
        "region_consultada": "sur",
    }


def test_informar_anomalia_404_es_ignorar(monkeypatch: pytest.MonkeyPatch, config: Config) -> None:
    def urlopen_falso(
        peticion: urllib.request.Request, timeout: float | None = None
    ) -> _RespuestaFalsa:
        raise urllib.error.HTTPError(peticion.full_url, 404, "no encontrado", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", urlopen_falso)
    cliente = ClienteValidacion(config)

    assert cliente.informar_anomalia(_evento()) == Decision.IGNORAR


def test_informar_anomalia_5xx_es_transitorio(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    def urlopen_falso(
        peticion: urllib.request.Request, timeout: float | None = None
    ) -> _RespuestaFalsa:
        raise urllib.error.HTTPError(peticion.full_url, 500, "error interno", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", urlopen_falso)
    cliente = ClienteValidacion(config)

    with pytest.raises(ErrorValidacionTransitoria):
        cliente.informar_anomalia(_evento())


def test_informar_anomalia_timeout_es_transitorio(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    def urlopen_falso(
        peticion: urllib.request.Request, timeout: float | None = None
    ) -> _RespuestaFalsa:
        raise TimeoutError("tiempo agotado")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen_falso)
    cliente = ClienteValidacion(config)

    with pytest.raises(ErrorValidacionTransitoria):
        cliente.informar_anomalia(_evento())


def test_informar_anomalia_sin_region_es_error_de_programacion(config: Config) -> None:
    cliente = ClienteValidacion(config)
    with pytest.raises(ValueError):
        cliente.informar_anomalia(_evento(region=None))
