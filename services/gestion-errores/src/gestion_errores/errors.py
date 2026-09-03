"""Validación del endpoint de incidentes y representación HTTP del error."""

from typing import Any


class ErrorValidacion(Exception):
    def __init__(self, campo: str, detalle: str) -> None:
        super().__init__(f"{campo} {detalle}")
        self.campo = campo
        self.detalle = detalle


def a_problem_json(
    error: ErrorValidacion,
    *,
    instance: str,
    correlation_id: str,
) -> tuple[dict[str, Any], int]:
    return (
        {
            "type": "https://solventa.co/errors/validacion",
            "title": "Incidente inválido",
            "status": 422,
            "detail": str(error),
            "instance": instance,
            "correlation_id": correlation_id,
        },
        422,
    )
