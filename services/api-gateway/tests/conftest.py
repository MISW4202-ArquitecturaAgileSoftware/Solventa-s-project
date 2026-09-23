from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient
from soporte_api_gateway import ClienteHttpDoble, configuracion

from api_gateway.app import crear_app


@pytest.fixture
def http() -> ClienteHttpDoble:
    return ClienteHttpDoble()


@pytest.fixture
def app(http: ClienteHttpDoble) -> Flask:
    return crear_app(configuracion(), http=http)


@pytest.fixture
def cliente(app: Flask) -> Iterator[FlaskClient]:
    with app.test_client() as c:
        yield c
