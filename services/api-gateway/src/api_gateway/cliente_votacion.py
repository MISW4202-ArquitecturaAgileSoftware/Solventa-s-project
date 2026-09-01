"""Cliente HTTP hacia Votación.

`urllib` de la biblioteca estándar: es un POST con timeout y sin reintentos.
Reintentar aquí sería un error de diseño —duplicaría el journey y gastaría el
presupuesto de ASR-12 dos veces—, así que no hace falta nada más rico.
"""

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from api_gateway.config import Config

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RespuestaVotacion:
    estado: int
    cuerpo: dict[str, Any]


class VotacionInalcanzableError(Exception):
    """Votación no respondió a tiempo o no se pudo contactar."""


def cotizar(
    config: Config,
    carga: bytes,
    *,
    correlation_id: str,
    request_id: str,
) -> RespuestaVotacion:
    peticion = urllib.request.Request(
        f"{config.url_votacion}/v1/cotizaciones",
        data=carga,
        headers={
            "Content-Type": "application/json",
            "X-Correlation-Id": correlation_id,
            "X-Request-Id": request_id,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=config.timeout_votacion_s) as respuesta:
            return RespuestaVotacion(respuesta.status, json.loads(respuesta.read()))
    except urllib.error.HTTPError as err:
        # Votación respondió con un 4xx/5xx: su cuerpo ya es problem+json y sus
        # detalles son aptos para el socio (nombres de campo, no trazas).
        try:
            return RespuestaVotacion(err.code, json.loads(err.read()))
        except ValueError, OSError:
            return RespuestaVotacion(err.code, {})
    except (urllib.error.URLError, TimeoutError, ValueError) as err:
        raise VotacionInalcanzableError(str(err)) from err
