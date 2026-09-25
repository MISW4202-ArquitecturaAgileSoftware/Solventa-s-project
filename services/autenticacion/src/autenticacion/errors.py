"""Excepciones de dominio y su traducción a RFC 9457 (`application/problem+json`)."""

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

    def __init__(self, campo: str, regla: str) -> None:
        super().__init__(f"{campo} {regla}")
        self.campo = campo


class ErrorCredenciales(ErrorSolventa):
    tipo = "credenciales"
    titulo = "Credenciales incorrectas"
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
