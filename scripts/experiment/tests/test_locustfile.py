"""El cierre al alcanzar N no puede correr en el greenlet del usuario."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from locustfile import _cerrar


def test_cerrar_con_ui_no_tira_los_usuarios(monkeypatch: pytest.MonkeyPatch) -> None:
    escrito: list[bool] = []
    monkeypatch.setattr("locustfile._escribir_resumen", lambda: escrito.append(True))
    runner = MagicMock()
    entorno = SimpleNamespace(runner=runner, web_ui=object())
    _cerrar(entorno)  # type: ignore[arg-type]
    runner.stop.assert_not_called()
    runner.quit.assert_not_called()
    assert escrito


def test_cerrar_headless_termina_el_proceso(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("locustfile._escribir_resumen", lambda: None)
    runner = MagicMock()
    entorno = SimpleNamespace(runner=runner, web_ui=None)
    _cerrar(entorno)  # type: ignore[arg-type]
    runner.quit.assert_called_once()
    runner.stop.assert_not_called()


def test_cerrar_sin_runner_no_lanza(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("locustfile._escribir_resumen", lambda: None)
    _cerrar(SimpleNamespace(runner=None, web_ui=None))  # type: ignore[arg-type]
