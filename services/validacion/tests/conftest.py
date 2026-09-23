from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_redis import RedisFalso
from flask import Flask
from flask.testing import FlaskClient
from soporte_validacion import configuracion

from validacion.app import crear_app


@pytest.fixture
def redis_falso() -> RedisFalso:
    return RedisFalso()


@pytest.fixture
def app(tmp_path: Path, redis_falso: RedisFalso) -> Flask:
    return crear_app(configuracion(tmp_path), cliente_redis=redis_falso)  # type: ignore[arg-type]


@pytest.fixture
def cliente(app: Flask) -> Iterator[FlaskClient]:
    with app.test_client() as c:
        yield c
