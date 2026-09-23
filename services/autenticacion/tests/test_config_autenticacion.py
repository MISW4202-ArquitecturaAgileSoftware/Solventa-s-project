from pathlib import Path

import pytest
from soporte_autenticacion import SECRETO

from autenticacion.config import desde_entorno


def test_valores_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    for nombre in ("RUTA_DB", "JWT_TTL_S", "MODO_EXPERIMENTO", "LOG_LEVEL"):
        monkeypatch.delenv(nombre, raising=False)
    monkeypatch.setenv("JWT_SECRET", SECRETO)

    config = desde_entorno()
    assert config.ruta_db == Path("/data/autenticacion.db")
    assert config.jwt_ttl_s == 3600
    assert config.modo_experimento is False
    assert config.log_level == "INFO"


def test_lee_el_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", SECRETO)
    monkeypatch.setenv("RUTA_DB", "/tmp/x.db")
    monkeypatch.setenv("JWT_TTL_S", "60")
    monkeypatch.setenv("MODO_EXPERIMENTO", "TRUE")

    config = desde_entorno()
    assert config.ruta_db == Path("/tmp/x.db")
    assert config.jwt_ttl_s == 60
    assert config.modo_experimento is True


def test_falta_el_secreto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        desde_entorno()


def test_secreto_corto_se_rechaza_al_arrancar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "corto")
    with pytest.raises(RuntimeError, match="32 bytes"):
        desde_entorno()


def test_ttl_no_positivo_se_rechaza(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", SECRETO)
    monkeypatch.setenv("JWT_TTL_S", "0")
    with pytest.raises(RuntimeError, match="JWT_TTL_S"):
        desde_entorno()
