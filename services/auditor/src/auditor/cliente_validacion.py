"""Cliente HTTP de Validación (`urllib` de la biblioteca estándar).

Solo llama a `POST /v1/anomalias`. Distingue dos clases de fallo, porque de
eso depende si el evento de auditoría se confirma o se reintenta:

- TRANSITORIO (red caída, timeout, 5xx, respuesta ilegible): reintentar puede
  funcionar. El evento queda pendiente y vuelve en el ciclo siguiente (§5.4).
- DEFINITIVO (404 empleado desconocido, 422 cuerpo rechazado): reintentar
  nunca lo arreglará. El evento se confirma y queda registrado en el log.
"""

import json
import urllib.error
import urllib.request
from typing import Any, Protocol

from auditor.config import Config
from auditor.contracts import CuerpoAnomalia, Decision

_DEFINITIVOS = frozenset({404, 422})


class ErrorValidacionRemota(Exception):
    def __init__(self, mensaje: str, *, definitivo: bool) -> None:
        super().__init__(mensaje)
        self.definitivo = definitivo


class ClienteValidacion(Protocol):
    def informar_anomalia(self, cuerpo: CuerpoAnomalia) -> Decision: ...


class ClienteValidacionHttp:
    RUTA = "/v1/anomalias"

    def __init__(self, config: Config) -> None:
        self._url = config.url_validacion.rstrip("/") + self.RUTA
        self._timeout_s = config.timeout_http_ms / 1000

    def informar_anomalia(self, cuerpo: CuerpoAnomalia) -> Decision:
        peticion = urllib.request.Request(
            self._url,
            data=json.dumps(cuerpo.a_dict(), ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Correlation-Id": cuerpo.correlation_id,
            },
        )
        try:
            with urllib.request.urlopen(peticion, timeout=self._timeout_s) as respuesta:
                if respuesta.status != 202:
                    raise ErrorValidacionRemota(
                        f"{self.RUTA} respondió {respuesta.status}, se esperaba 202",
                        definitivo=False,
                    )
                datos = json.loads(respuesta.read())
        except urllib.error.HTTPError as err:
            raise ErrorValidacionRemota(
                f"{self.RUTA} respondió {err.code}", definitivo=err.code in _DEFINITIVOS
            ) from err
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
            raise ErrorValidacionRemota(
                f"fallo de red hacia {self.RUTA}: {err}", definitivo=False
            ) from err
        return _decision(datos, cuerpo.evento_id)


def _decision(datos: Any, evento_id: str) -> Decision:
    if not isinstance(datos, dict):
        raise ErrorValidacionRemota("la respuesta no es un objeto JSON", definitivo=False)
    if datos.get("evento_id") != evento_id:
        raise ErrorValidacionRemota(
            f"la respuesta es de otro evento: {datos.get('evento_id')!r}", definitivo=False
        )
    crudo = datos.get("decision")
    try:
        return Decision(str(crudo))
    except ValueError as err:
        raise ErrorValidacionRemota(f"decisión desconocida: {crudo!r}", definitivo=False) from err
