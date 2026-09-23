"""Excepciones de dominio y su traducción a RFC 9457 (`application/problem+json`).

Los `type` son los de PLAN-IMPLEMENTACION.md §3.1. Los 401 se distinguen por
`type`, no por el código: el experimento cuenta `empleado-bloqueado` y
`credenciales` por separado.
"""

from typing import Any

BASE_TIPOS = "https://solventa.co/errors/"


class ErrorSolventa(Exception):
    tipo = "interno"
    titulo = "Error interno"
    estado = 500

    def __init__(self, detalle: str) -> None:
        super().__init__(detalle)
        self.detalle = detalle


class ErrorValidacion(ErrorSolventa):
    tipo = "validacion"
    titulo = "Solicitud inválida"
    estado = 422


class ErrorCredenciales(ErrorSolventa):
    tipo = "credenciales"
    titulo = "Usuario o contraseña incorrectos"
    estado = 401


class ErrorEmpleadoBloqueado(ErrorSolventa):
    tipo = "empleado-bloqueado"
    titulo = "El empleado está bloqueado"
    estado = 401


class ErrorNoEncontrado(ErrorSolventa):
    tipo = "recurso-no-encontrado"
    titulo = "Recurso no encontrado"
    estado = 404


def a_problem_json(
    err: ErrorSolventa, instance: str, correlation_id: str
) -> tuple[dict[str, Any], int]:
    return (
        {
            "type": BASE_TIPOS + err.tipo,
            "title": err.titulo,
            "status": err.estado,
            "detail": err.detalle,
            "instance": instance,
            "correlation_id": correlation_id,
        },
        err.estado,
    )


def problem_json_http(
    estado: int, titulo: str, detalle: str, instance: str, correlation_id: str
) -> dict[str, Any]:
    """Errores del protocolo HTTP sin semántica propia (ruta inexistente, método
    no admitido, fallo no previsto). RFC 9457 §4.2.1: `type` = `about:blank`."""
    return {
        "type": "about:blank",
        "title": titulo,
        "status": estado,
        "detail": detalle,
        "instance": instance,
        "correlation_id": correlation_id,
    }
