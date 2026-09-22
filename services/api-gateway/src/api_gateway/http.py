"""Cliente HTTP interno hacia Autenticación y Validación.

`ClienteHttp` es la interfaz: una única operación, deliberadamente pequeña,
para que los tests inyecten un doble sin tocar la red. `ClienteHttpReal` es la
única implementación, y es la que traduce los modos de fallo de `requests` a
`ErrorUpstream` (PLAN-IMPLEMENTACION.md §3.1).
"""

from dataclasses import dataclass
from typing import Any, Protocol

import requests  # type: ignore[import-untyped]

from api_gateway.errors import ErrorUpstream

CABECERA_CORRELACION = "X-Correlation-Id"


@dataclass(frozen=True, slots=True)
class RespuestaInterna:
    estado: int
    cuerpo: Any
    content_type: str


class ClienteHttp(Protocol):
    def post(self, url: str, json: Any, correlation_id: str) -> RespuestaInterna: ...


class ClienteHttpReal:
    def __init__(self, timeout_s: float) -> None:
        self._timeout_s = timeout_s
        self._sesion = requests.Session()

    def post(self, url: str, json: Any, correlation_id: str) -> RespuestaInterna:
        try:
            respuesta = self._sesion.post(
                url,
                json=json,
                headers={CABECERA_CORRELACION: correlation_id},
                timeout=self._timeout_s,
            )
        except requests.Timeout as err:
            raise ErrorUpstream(f"{url} no respondió en el tiempo de espera", 504) from err
        except requests.ConnectionError as err:
            raise ErrorUpstream(f"{url} rechazó la conexión", 503) from err
        except requests.RequestException as err:
            # Cualquier otro fallo de `requests` (redirecciones, SSL…): no
            # documentado explícitamente en §3.1, pero sigue siendo el
            # servicio interno el que falló, no la petición del cliente.
            raise ErrorUpstream(f"{url} falló: {err}", 502) from err

        try:
            cuerpo = respuesta.json()
        except ValueError as err:
            raise ErrorUpstream(f"{url} respondió un cuerpo no JSON", 502) from err

        return RespuestaInterna(
            estado=respuesta.status_code,
            cuerpo=cuerpo,
            content_type=respuesta.headers.get("Content-Type", "application/json"),
        )
