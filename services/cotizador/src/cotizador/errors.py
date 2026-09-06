"""Excepciones propias del cálculo y del tarifario."""


class ErrorValidacion(Exception):
    """La solicitud no cumple el contrato de entrada."""

    def __init__(self, campo: str, detalle: str) -> None:
        super().__init__(f"{campo} {detalle}")
        self.campo = campo
        self.detalle = detalle


class TarifarioDesconocido(Exception):
    """Se pidió una versión de tarifario que no existe."""
