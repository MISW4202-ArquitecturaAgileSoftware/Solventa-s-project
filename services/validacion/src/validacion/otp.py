"""Generación y verificación del código OTP (PLAN-IMPLEMENTACION.md §5.1, §5.2).

Un solo intento, sin expiración: limitaciones aceptadas para el experimento
(§7). El código nace y se compara como texto para conservar los ceros a la
izquierda.
"""

import hmac
import secrets

_DIGITOS = 6
_TOPE = 10**_DIGITOS


def generar_codigo() -> str:
    return f"{secrets.randbelow(_TOPE):0{_DIGITOS}d}"


def coincide(codigo_pendiente: str, codigo_recibido: str) -> bool:
    """Comparación en tiempo constante: el código es, en la práctica, un secreto."""
    return hmac.compare_digest(codigo_pendiente, codigo_recibido)
