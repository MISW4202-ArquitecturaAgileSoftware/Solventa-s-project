"""Hash de contraseñas con scrypt y sal por empleado.

Las contraseñas son de prueba, pero el servicio no debe almacenarlas en claro:
la base de Autenticación es justo lo que el atacante del experimento altera.
"""

import hashlib
import hmac
import secrets

_N = 2**14
_R = 8
_P = 1


def hashear(password: str) -> str:
    sal = secrets.token_bytes(16)
    digesto = hashlib.scrypt(password.encode(), salt=sal, n=_N, r=_R, p=_P)
    return f"{sal.hex()}${digesto.hex()}"


def verificar(password: str, almacenado: str) -> bool:
    sal_hex, _, digesto_hex = almacenado.partition("$")
    if not sal_hex or not digesto_hex:
        return False
    digesto = hashlib.scrypt(password.encode(), salt=bytes.fromhex(sal_hex), n=_N, r=_R, p=_P)
    return hmac.compare_digest(digesto.hex(), digesto_hex)
