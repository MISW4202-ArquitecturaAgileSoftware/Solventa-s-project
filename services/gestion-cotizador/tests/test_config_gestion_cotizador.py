"""Configuración del worker: variable obligatoria, defectos y claves derivadas."""

import pytest

from gestion_cotizador.config import desde_entorno


@pytest.fixture(autouse=True)
def _entorno_minimo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.delenv("GRUPO", raising=False)
    monkeypatch.delenv("CONSUMIDOR", raising=False)


def test_redis_url_ausente_impide_arrancar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL")
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        desde_entorno()


def test_valores_por_defecto() -> None:
    config = desde_entorno()

    assert config.stream_cotizador == "sol:cotizador"
    assert config.prefijo_respuestas == "resp"
    assert config.ttl_respuestas_s == 60
    assert config.tarifario_version == "2026.02"
    assert config.grupo == "gestion-cotizador"
    assert config.consumidor
    assert config.block_ms == 1000


def test_consumidor_por_defecto_es_el_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    monkeypatch.delenv("CONSUMIDOR", raising=False)
    assert desde_entorno().consumidor == socket.gethostname()


def test_variables_declaradas_reemplazan_el_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STREAM_COTIZADOR", "otro:stream")
    monkeypatch.setenv("GRUPO", "otro-grupo")
    monkeypatch.setenv("CONSUMIDOR", "worker-1")
    monkeypatch.setenv("BLOCK_MS", "500")

    config = desde_entorno()

    assert config.stream_cotizador == "otro:stream"
    assert config.grupo == "otro-grupo"
    assert config.consumidor == "worker-1"
    assert config.block_ms == 500


def test_la_clave_de_respuestas_lleva_el_correlation_id() -> None:
    config = desde_entorno()
    assert config.clave_respuestas("019a05aa") == "resp:019a05aa"
