"""Excepciones que el oráculo puede lanzar al parsear o calcular."""


class ErrorSolventa(Exception):
    """Raíz de la jerarquía. Nunca se lanza directamente."""


class ErrorValidacion(ErrorSolventa):
    """La solicitud no cumple el contrato de entrada."""

    def __init__(self, campo: str, detalle: str) -> None:
        super().__init__(f"{campo} {detalle}")
        self.campo = campo
        self.detalle = detalle


class TarifarioDesconocido(ErrorSolventa):
    """Se pidió una versión de tarifario que no existe."""
