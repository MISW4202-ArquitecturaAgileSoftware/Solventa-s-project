"""`ClienteValidacionHttp` contra un servidor HTTP real en un hilo."""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from soporte_auditor import configuracion

from auditor.cliente_validacion import ClienteValidacionHttp, ErrorValidacionRemota
from auditor.contracts import CuerpoAnomalia, Decision

CUERPO = CuerpoAnomalia(
    evento_id="a-1",
    correlation_id="c-1",
    employee_id="E-ASN-01",
    session_id="s-1",
    accion="CONSULTA_POLIZA",
    region_consultada="sur",
)


class _Manejador(BaseHTTPRequestHandler):
    respuesta: ClassVar[tuple[int, Any]] = (202, {})
    recibidas: ClassVar[list[tuple[str, dict[str, str], Any]]] = []

    def do_POST(self) -> None:
        largo = int(self.headers.get("Content-Length", "0"))
        self.recibidas.append(
            (self.path, dict(self.headers.items()), json.loads(self.rfile.read(largo)))
        )
        estado, cuerpo = self.respuesta
        datos = cuerpo.encode() if isinstance(cuerpo, str) else json.dumps(cuerpo).encode()
        self.send_response(estado)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, *_args: Any) -> None:
        return


@pytest.fixture
def servidor() -> Iterator[str]:
    _Manejador.recibidas = []
    http = ThreadingHTTPServer(("127.0.0.1", 0), _Manejador)
    hilo = threading.Thread(target=http.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{http.server_address[1]}"
    http.shutdown()
    http.server_close()


def _cliente(tmp_path: Path, url: str) -> ClienteValidacionHttp:
    return ClienteValidacionHttp(configuracion(tmp_path, url_validacion=url, timeout_http_ms=500))


@pytest.mark.parametrize("decision", ["ALERTAR", "REVOCAR"])
def test_decision_y_peticion(tmp_path: Path, servidor: str, decision: str) -> None:
    _Manejador.respuesta = (202, {"evento_id": "a-1", "decision": decision})

    assert _cliente(tmp_path, servidor + "/").informar_anomalia(CUERPO) is Decision(decision)

    ruta, cabeceras, cuerpo = _Manejador.recibidas[0]
    assert ruta == "/v1/anomalias"
    assert cabeceras["Content-Type"] == "application/json"
    assert cabeceras["X-Correlation-Id"] == "c-1"
    assert cuerpo == CUERPO.a_dict()


@pytest.mark.parametrize(
    ("estado", "cuerpo", "definitivo"),
    [
        (404, {"type": "https://solventa.co/errors/recurso-no-encontrado"}, True),
        (422, {"type": "https://solventa.co/errors/validacion"}, True),
        (500, {}, False),
        (503, {}, False),
        (200, {"evento_id": "a-1", "decision": "ALERTAR"}, False),
        (202, "no es json", False),
        (202, ["lista"], False),
        (202, {"evento_id": "otro", "decision": "ALERTAR"}, False),
        (202, {"evento_id": "a-1", "decision": "IGNORAR"}, False),
    ],
)
def test_clasifica_los_fallos(
    tmp_path: Path, servidor: str, estado: int, cuerpo: Any, definitivo: bool
) -> None:
    _Manejador.respuesta = (estado, cuerpo)
    with pytest.raises(ErrorValidacionRemota) as err:
        _cliente(tmp_path, servidor).informar_anomalia(CUERPO)
    assert err.value.definitivo is definitivo


def test_validacion_inalcanzable_es_transitorio(tmp_path: Path) -> None:
    with pytest.raises(ErrorValidacionRemota) as err:
        _cliente(tmp_path, "http://127.0.0.1:9").informar_anomalia(CUERPO)
    assert err.value.definitivo is False
