"""Contrato HTTP entre Votación y Gestión de Errores."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from votacion.contracts import Incidente, TipoIncidente
from votacion.reportero import Reportero


class RespuestaHTTP:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "RespuestaHTTP":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _reportero() -> Reportero:
    reportero = Reportero.__new__(Reportero)
    reportero._config = SimpleNamespace(  # type: ignore[attr-defined]
        url_gestion_errores="http://gestion-errores:8000",
        timeout_reporte_s=2.0,
    )
    return reportero


def _incidente() -> Incidente:
    return Incidente(
        correlation_id="01a05aa8-24a1-753e-b019-a0810d66a3f6",
        tipo=TipoIncidente.DIVERGENCIA_RESULTADO,
        detectado_en=datetime(2026, 8, 31, tzinfo=UTC),
    )


def test_acepta_201_como_confirmacion_de_creacion(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def responder(*_args: Any, **_kwargs: Any) -> RespuestaHTTP:
        return RespuestaHTTP(201)

    monkeypatch.setattr("urllib.request.urlopen", responder)

    _reportero()._enviar(_incidente())

    assert "no se pudo reportar" not in caplog.text


def test_un_estado_distinto_de_201_se_registra_como_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def responder(*_args: Any, **_kwargs: Any) -> RespuestaHTTP:
        return RespuestaHTTP(202)

    monkeypatch.setattr("urllib.request.urlopen", responder)

    _reportero()._enviar(_incidente())

    assert any(
        getattr(registro, "motivo", None) == "estado inesperado 202"
        for registro in caplog.records
    )
