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


class ErrorOperacionNoAutorizada(ErrorSolventa):
    tipo = "operacion-no-autorizada"
    titulo = "Operación no autorizada"
    estado = 403


class ErrorOtpFallido(ErrorSolventa):
    tipo = "otp-fallido"
    titulo = "Código OTP incorrecto"
    estado = 403


class ErrorOtpPendiente(ErrorSolventa):
    tipo = "otp-pendiente"
    titulo = "Ya hay un OTP pendiente para la sesión"
    estado = 409


class ErrorSinOtpPendiente(ErrorSolventa):
    tipo = "sin-otp-pendiente"
    titulo = "No hay un OTP pendiente para la sesión"
    estado = 404


class ErrorNoEncontrado(ErrorSolventa):
    tipo = "recurso-no-encontrado"
    titulo = "Recurso no encontrado"
    estado = 404


class ErrorEstadoInvalido(ErrorSolventa):
    tipo = "estado-invalido"
    titulo = "Estado inválido para la operación"
    estado = 409


class ErrorTimeoutOperacion(ErrorSolventa):
    tipo = "timeout-operacion"
    titulo = "El worker no respondió a tiempo"
    estado = 504


class ErrorUpstream(ErrorSolventa):
    tipo = "upstream"
    titulo = "El worker falló internamente"
    estado = 502


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
