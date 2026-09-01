"""Configuración del gateway."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Config:
    url_votacion: str
    log_level: str

    #: Presupuesto de la llamada a Votación. Debe superar el presupuesto de
    #: consenso (250 ms) con holgura para el ida y vuelta, pero quedar dentro de
    #: los 300 ms que ASR-12 concede al journey completo.
    timeout_votacion_s: float

    #: ASR-12 exige responder «sin exponer el error». Con esto en false el
    #: gateway retira el bloque `consenso` aunque Votación lo haya incluido:
    #: es la última barrera antes del socio.
    expose_consensus: bool

    #: Peticiones por minuto y socio. En memoria y por proceso; suficiente para
    #: el experimento. Un despliegue real lo llevaría al proxy de borde o a un
    #: contador compartido, porque con varios gateways cada uno contaría aparte.
    limite_por_minuto: int


def _requerida(nombre: str) -> str:
    valor = os.environ.get(nombre)
    if not valor:
        raise RuntimeError(f"falta la variable de entorno {nombre}")
    return valor


def desde_entorno() -> Config:
    return Config(
        url_votacion=_requerida("URL_VOTACION"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        timeout_votacion_s=float(os.environ.get("TIMEOUT_VOTACION_MS", "300")) / 1000,
        expose_consensus=os.environ.get("EXPOSE_CONSENSUS", "false").lower() == "true",
        limite_por_minuto=int(os.environ.get("LIMITE_POR_MINUTO", "6000")),
    )
