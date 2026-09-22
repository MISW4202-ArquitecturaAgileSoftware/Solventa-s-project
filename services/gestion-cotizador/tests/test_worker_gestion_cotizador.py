"""Recuperación del grupo, aislamiento de mensajes corruptos y cierre del worker."""

import signal
import threading
from collections.abc import Callable
from types import FrameType
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from redis import Redis
from redis.exceptions import ResponseError
from soporte_gestion_cotizador import configuracion

from gestion_cotizador import __main__ as arranque
from gestion_cotizador import consumer
from gestion_cotizador.config import Config


def test_grupo_existente_conserva_su_posicion() -> None:
    cliente = MagicMock(spec=Redis)
    cliente.xgroup_create.side_effect = ResponseError("BUSYGROUP Consumer Group already exists")
    consumer.asegurar_grupo(cliente, configuracion())
    cliente.xgroup_destroy.assert_not_called()


def test_error_de_grupo_distinto_de_busygroup_se_propaga() -> None:
    cliente = MagicMock(spec=Redis)
    cliente.xgroup_create.side_effect = ResponseError("NOPERM")
    with pytest.raises(ResponseError, match="NOPERM"):
        consumer.asegurar_grupo(cliente, configuracion())


def test_bucle_recrea_grupo_y_continua_tras_mensaje_corrupto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = MagicMock(spec=Redis)
    parar = threading.Event()
    procesados: list[str] = []
    lecturas = 0

    def leer(**_opciones: Any) -> list[Any]:
        nonlocal lecturas
        lecturas += 1
        if lecturas == 1:
            raise ResponseError("NOGROUP No such key or consumer group")
        parar.set()
        return [("sol:cotizador", [("1-0", {"data": "corrupto"}), ("2-0", {"data": "ok"})])]

    def procesar(_redis: Redis, _config: Config, mid: str, _campos: dict[str, str]) -> None:
        if mid == "1-0":
            raise ValueError("mensaje ilegible")
        procesados.append(mid)

    cliente.xreadgroup.side_effect = leer
    monkeypatch.setattr(consumer, "procesar", procesar)
    consumer.bucle(cliente, configuracion(), parar)
    assert cliente.xgroup_create.call_count == 2
    assert procesados == ["2-0"]
    cliente.xack.assert_not_called()


@pytest.mark.parametrize("fallar", [False, True])
def test_arranque_atiende_sigterm_y_cierra_redis(
    monkeypatch: pytest.MonkeyPatch, fallar: bool
) -> None:
    cliente = MagicMock(spec=Redis)
    manejadores: dict[int, Callable[[int, FrameType | None], None]] = {}

    def registrar(numero: int, manejador: Callable[[int, FrameType | None], None]) -> None:
        manejadores[numero] = manejador

    def ejecutar(redis: Redis, _config: Config, parar: threading.Event) -> None:
        assert redis is cliente
        assert not parar.is_set()
        manejadores[signal.SIGTERM](signal.SIGTERM, None)
        assert parar.is_set()
        if fallar:
            raise RuntimeError("fallo del consumidor")

    monkeypatch.setattr(arranque, "desde_entorno", configuracion)
    monkeypatch.setattr(signal, "signal", registrar)
    monkeypatch.setattr(Redis, "from_url", lambda *_a, **_kw: cast(Redis, cliente))
    monkeypatch.setattr(consumer, "bucle", ejecutar)
    if fallar:
        with pytest.raises(RuntimeError, match="fallo del consumidor"):
            arranque.main()
    else:
        assert arranque.main() == 0
    cliente.close.assert_called_once()
