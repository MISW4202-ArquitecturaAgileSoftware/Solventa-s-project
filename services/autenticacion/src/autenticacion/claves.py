"""Hash de contraseñas con `hashlib.scrypt` y sal por empleado (§3.3).

La contraseña es de prueba, pero el servicio no la almacena en claro. El hash
se guarda autodescriptivo — `scrypt$n$r$p$sal$derivada`, en base64 — para que
cambiar el coste en el futuro no invalide los hashes ya guardados.
"""

import base64
import hashlib
import hmac
import secrets
from functools import cache

#: Coste recomendado para login interactivo (≈16 MiB de memoria por hash).
N = 2**14
R = 8
P = 1
LONGITUD_SAL = 16
LONGITUD_DERIVADA = 32
_PREFIJO = "scrypt"


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode("ascii")


def _derivar(password: str, sal: bytes, n: int, r: int, p: int, longitud: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=sal, n=n, r=r, p=p, dklen=longitud)


def hashear(password: str) -> str:
    sal = secrets.token_bytes(LONGITUD_SAL)
    derivada = _derivar(password, sal, N, R, P, LONGITUD_DERIVADA)
    return f"{_PREFIJO}${N}${R}${P}${_b64(sal)}${_b64(derivada)}"


def verificar(password: str, hash_guardado: str) -> bool:
    """Compara en tiempo constante. Un hash con formato inesperado nunca valida."""
    try:
        prefijo, n, r, p, sal, derivada = hash_guardado.split("$")
        if prefijo != _PREFIJO:
            return False
        esperada = base64.b64decode(derivada, validate=True)
        calculada = _derivar(
            password, base64.b64decode(sal, validate=True), int(n), int(r), int(p), len(esperada)
        )
    except ValueError:
        return False
    return hmac.compare_digest(calculada, esperada)


@cache
def _hash_senuelo() -> str:
    return hashear(secrets.token_urlsafe(16))


def gastar_tiempo_equivalente(password: str) -> None:
    """Para un usuario inexistente se paga el mismo scrypt que para uno real:
    así el tiempo de respuesta no revela qué usuarios existen."""
    verificar(password, _hash_senuelo())
