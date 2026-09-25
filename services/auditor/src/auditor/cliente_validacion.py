"""Cliente HTTP de Validación (`urllib` de la biblioteca estándar).

Un worker no necesita `requests`: es un único POST con timeout y sin reintentos
en línea. El reintento lo hace el ciclo siguiente, al no hacer `XACK` ante un
fallo transitorio (ver `ciclo.py`).
"""

import json
import logging
import urllib.error
import urllib.request
from typing import Protocol

from auditor.config import Config
from auditor.contracts import CuerpoAnomalia, Decision, EventoAuditoria, RespuestaAnomalia

log = logging.getLogger(__name__)

_RUTA_ANOMALIAS = "/v1/anomalias"


class ErrorValidacionTransitoria(Exception):
    """Fallo de red, timeout o 5xx: se asume recuperable en el ciclo siguiente."""


class ProtocoloValidacion(Protocol):
    def informar_anomalia(self, evento: EventoAuditoria) -> Decision: ...


class ClienteValidacion:
    def __init__(self, config: Config) -> None:
        self._config = config

    def informar_anomalia(self, evento: EventoAuditoria) -> Decision:
        if evento.recurso.region is None:
            raise ValueError("un evento sin región no se informa a Validación")

        cuerpo = CuerpoAnomalia(
            evento_id=evento.evento_id,
            correlation_id=evento.correlation_id,
            employee_id=evento.actor.employee_id,
            session_id=evento.actor.session_id,
            accion=evento.accion,
            region_consultada=evento.recurso.region,
        )
        peticion = urllib.request.Request(
            self._config.url_validacion + _RUTA_ANOMALIAS,
            data=json.dumps(cuerpo.a_dict(), ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Correlation-Id": evento.correlation_id,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                peticion, timeout=self._config.timeout_http_ms / 1000
            ) as respuesta:
                if respuesta.status != 202:
                    raise ErrorValidacionTransitoria(f"estado inesperado {respuesta.status}")
                crudo = json.loads(respuesta.read())
        except urllib.error.HTTPError as err:
            if err.code == 404:
                log.warning(
                    "empleado desconocido para Validación",
                    extra={"employee_id": evento.actor.employee_id},
                )
                return Decision.IGNORAR
            raise ErrorValidacionTransitoria(f"estado {err.code}") from err
        except (urllib.error.URLError, TimeoutError) as err:
            raise ErrorValidacionTransitoria(str(err)) from err

        return RespuestaAnomalia.desde_dict(crudo).decision
