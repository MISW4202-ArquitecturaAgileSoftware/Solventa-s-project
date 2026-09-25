from collections.abc import Iterator
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient
from soporte_autenticacion import configuracion

from autenticacion.app import crear_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return crear_app(configuracion(tmp_path))


@pytest.fixture
def cliente(app: Flask) -> Iterator[FlaskClient]:
    with app.test_client() as c:
        yield c
