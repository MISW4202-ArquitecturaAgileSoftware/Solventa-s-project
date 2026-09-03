"""Identificación de peticiones.

Se usa UUIDv7 y no v4 porque es ordenado en el tiempo: los identificadores
ordenan solos en los logs y en los Streams de Redis, lo que hace depurable el
experimento de votación. Disponible en la biblioteca estándar desde Python 3.14.
"""

import uuid


def nuevo_correlation_id() -> str:
    """Identificador del journey completo, generado por el API Gateway."""
    return str(uuid.uuid7())


def es_correlation_id_valido(valor: str) -> bool:
    """Verifica que el valor sea un UUID bien formado.

    No exige que sea versión 7: un socio puede enviar su propio identificador y
    lo conservamos tal cual.
    """
    try:
        uuid.UUID(valor)
    except ValueError, AttributeError, TypeError:
        return False
    return True
