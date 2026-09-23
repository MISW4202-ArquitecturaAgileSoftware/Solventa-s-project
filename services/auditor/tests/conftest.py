from pathlib import Path

import pytest
from soporte_auditor import RedisStreamsFalso, RelojFalso, ValidacionFalsa, configuracion

from auditor import seed
from auditor.config import Config
from auditor.repositorio import Repositorio


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return configuracion(tmp_path)


@pytest.fixture
def repositorio(config: Config) -> Repositorio:
    repositorio = Repositorio(config.ruta_db)
    repositorio.inicializar()
    seed.sembrar(repositorio)
    return repositorio


@pytest.fixture
def cola() -> RedisStreamsFalso:
    return RedisStreamsFalso()


@pytest.fixture
def validacion() -> ValidacionFalsa:
    return ValidacionFalsa()


@pytest.fixture
def reloj() -> RelojFalso:
    return RelojFalso()
