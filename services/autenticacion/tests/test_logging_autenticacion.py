import json
import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from autenticacion.structured_logging import FormateadorJson, contexto_correlacion


def _record(creado: datetime) -> logging.LogRecord:
    record = logging.LogRecord("prueba", logging.INFO, __file__, 1, "hola", None, None)
    record.created = creado.timestamp()
    record.empleado = "E-ASN-01"
    return record


@pytest.fixture
def zona_local_bogota(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TZ", "America/Bogota")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.usefixtures("zona_local_bogota")
def test_momento_en_utc_con_milisegundos_reales() -> None:
    # Una zona local distinta de UTC no debe cambiar el instante registrado.
    creado = datetime(2026, 9, 23, 17, 17, 42, 456_789, tzinfo=UTC)

    linea = json.loads(FormateadorJson("autenticacion").format(_record(creado)))

    assert linea["momento"] == "2026-09-23T17:17:42.456Z"


def test_linea_lleva_correlation_id_y_extras() -> None:
    with contexto_correlacion("cid-1"):
        linea = json.loads(FormateadorJson("autenticacion").format(_record(datetime.now(tz=UTC))))
    assert linea["correlation_id"] == "cid-1"
    assert linea["servicio"] == "autenticacion"
    assert linea["mensaje"] == "hola"
    assert linea["empleado"] == "E-ASN-01"
