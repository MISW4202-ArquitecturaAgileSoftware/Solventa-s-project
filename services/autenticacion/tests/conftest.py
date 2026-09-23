import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient
from soporte_autenticacion import RelojFalso, configuracion

from autenticacion import seed
from autenticacion.app import crear_app
from autenticacion.repositorio import Repositorio


@pytest.fixture(scope="session")
def base_sembrada(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Una base sembrada por sesión de pytest: scrypt cuesta decenas de ms por
    empleado y sembrar 13 en cada test haría la suite lenta sin probar más."""
    directorio = tmp_path_factory.mktemp("plantilla")
    repositorio = Repositorio(directorio / "autenticacion.db")
    repositorio.inicializar()
    seed.sembrar(repositorio)
    return directorio


@pytest.fixture
def reloj() -> RelojFalso:
    return RelojFalso()


FabricaApp = Callable[..., Flask]


@pytest.fixture
def fabrica_app(tmp_path: Path, base_sembrada: Path, reloj: RelojFalso) -> FabricaApp:
    """Crea la app sobre una copia de la base sembrada; los argumentos con
    nombre sobrescriben campos de la configuración."""

    def fabricar(**cambios: object) -> Flask:
        # Se copian también -wal/-shm si existen: la plantilla está en modo WAL.
        for archivo in base_sembrada.iterdir():
            shutil.copy(archivo, tmp_path / archivo.name)
        return crear_app(configuracion(tmp_path, **cambios), reloj=reloj)

    return fabricar


@pytest.fixture
def app(fabrica_app: FabricaApp) -> Flask:
    return fabrica_app()


@pytest.fixture
def cliente(app: Flask) -> Iterator[FlaskClient]:
    with app.test_client() as c:
        yield c
