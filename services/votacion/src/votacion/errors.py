"""Excepciones de dominio y su traducción a RFC 9457 (application/problem+json).

El dominio lanza excepciones; la capa de transporte las traduce. Ningún módulo
de dominio importa Flask ni conoce códigos HTTP: el mapeo vive aquí, en un solo
sitio, y las vistas se limitan a invocarlo.
"""

from typing import Any

BASE_TIPO = "https://solventa.co/errors"


class ErrorSolventa(Exception):
    """Raíz de la jerarquía. Nunca se lanza directamente."""

    tipo: str = f"{BASE_TIPO}/interno"
    titulo: str = "Error interno"
    estado: int = 500


class ErrorValidacion(ErrorSolventa):
    """La solicitud no cumple el contrato de entrada."""

    tipo = f"{BASE_TIPO}/validacion"
    titulo = "Solicitud de cotización inválida"
    estado = 422

    def __init__(self, campo: str, detalle: str) -> None:
        super().__init__(f"{campo} {detalle}")
        self.campo = campo
        self.detalle = detalle


class ErrorSinConsenso(ErrorSolventa):
    """Hubo respuestas, pero ningún resultado alcanzó el quórum configurado."""

    tipo = f"{BASE_TIPO}/sin-consenso"
    titulo = "No fue posible resolver una cotización confiable"
    estado = 503


class ErrorTimeoutCotizacion(ErrorSolventa):
    """Venció el presupuesto de recolección sin respuestas utilizables."""

    tipo = f"{BASE_TIPO}/timeout-cotizacion"
    titulo = "La cotización excedió su presupuesto de tiempo"
    estado = 504


def a_problem_json(
    err: ErrorSolventa,
    *,
    instance: str,
    correlation_id: str,
    titulo: str | None = None,
) -> tuple[dict[str, Any], int]:
    """Traduce una excepción de dominio al cuerpo y estado de una respuesta RFC 9457.

    El `detail` sale del mensaje de la excepción, que nunca debe contener trazas
    ni nombres de host: lo lee el socio.

    `titulo` permite a un servicio ajustar el encabezado a su propio recurso:
    el mismo `ErrorValidacion` significa "solicitud de cotización inválida" en
    el gateway e "incidente inválido" en el registro de errores.
    """
    cuerpo: dict[str, Any] = {
        "type": err.tipo,
        "title": titulo or err.titulo,
        "status": err.estado,
        "detail": str(err),
        "instance": instance,
        "correlation_id": correlation_id,
    }
    return cuerpo, err.estado
