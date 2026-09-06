"""Configuración del worker: identidad, nombres derivados y variables obligatorias."""

import pytest

from cotizador.config import desde_entorno


@pytest.fixture(autouse=True)
def _entorno_minimo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COTIZADOR_ID", "B")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")


def test_el_grupo_se_deriva_de_la_identidad() -> None:
    """Un consumer group por réplica: de ahí sale el fan-out."""
    assert desde_entorno().grupo == "grupo-b"


def test_la_clave_de_respuestas_lleva_el_correlation_id() -> None:
    config = desde_entorno()
    assert config.clave_respuestas("01a05aa8") == "cot:resp:01a05aa8"


def test_sin_fallo_configurado_la_replica_esta_sana() -> None:
    assert desde_entorno().fault_mode == "none"


@pytest.mark.parametrize("variable", ["COTIZADOR_ID", "REDIS_URL"])
def test_variable_obligatoria_ausente(monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
    """Una réplica sin identidad no puede participar en una votación: debe
    negarse a arrancar en vez de hacerlo con un valor por defecto."""
    monkeypatch.delenv(variable)
    with pytest.raises(RuntimeError, match=variable):
        desde_entorno()


def test_el_consumidor_se_deriva_de_la_identidad() -> None:
    assert desde_entorno().consumidor == "consumidor-b"


def test_el_bloqueo_es_corto_para_atender_sigterm() -> None:
    """El bucle solo puede ver la señal de parada al vencer su `block`."""
    assert desde_entorno().block_ms <= 2000
