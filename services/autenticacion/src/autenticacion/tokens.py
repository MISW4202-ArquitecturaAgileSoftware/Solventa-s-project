"""Emisión y verificación de JWT HS256 con PyJWT (§3.3).

Claims: `sub` (employee_id), `sid` (session_id), `rol`, `iat`, `exp`.

La expiración se comprueba aquí y no dentro de PyJWT por dos razones: la
respuesta `EXPIRADA` debe llevar el `session_id`, que solo se conoce tras
validar la firma, y el reloj se inyecta para poder probarla sin esperar.
"""

from dataclasses import dataclass
from datetime import datetime

import jwt

from autenticacion.contracts import Rol, desde_epoch

ALGORITMO = "HS256"
_CLAIMS_OBLIGATORIOS = ["sub", "sid", "rol", "iat", "exp"]


class TokenInvalido(Exception):
    """Firma inválida, algoritmo distinto de HS256, formato roto o claims ausentes."""


class TokenExpirado(Exception):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"token de la sesión {session_id} expirado")
        self.session_id = session_id


@dataclass(frozen=True, slots=True)
class Claims:
    employee_id: str
    session_id: str
    rol: Rol
    emitido_en: datetime
    expira_en: datetime


def emitir(
    secreto: str, ttl_s: int, employee_id: str, session_id: str, rol: Rol, ahora: datetime
) -> tuple[str, Claims]:
    # Los claims de tiempo son enteros (RFC 7519 NumericDate); se trunca `ahora`
    # para que lo guardado en `sesiones` y lo firmado coincidan al segundo.
    iat = int(ahora.timestamp())
    exp = iat + ttl_s
    token = jwt.encode(
        {"sub": employee_id, "sid": session_id, "rol": rol.value, "iat": iat, "exp": exp},
        secreto,
        algorithm=ALGORITMO,
    )
    return token, Claims(
        employee_id=employee_id,
        session_id=session_id,
        rol=rol,
        emitido_en=desde_epoch(iat),
        expira_en=desde_epoch(exp),
    )


def verificar(token: str, secreto: str, ahora: datetime) -> Claims:
    try:
        crudos = jwt.decode(
            token,
            secreto,
            # Lista cerrada: impide `alg: none` y la confusión de algoritmos.
            algorithms=[ALGORITMO],
            # El tiempo lo juzga este módulo con el reloj inyectado, no PyJWT
            # con el reloj del sistema.
            options={"require": _CLAIMS_OBLIGATORIOS, "verify_exp": False, "verify_iat": False},
        )
    except jwt.PyJWTError as err:
        raise TokenInvalido(str(err)) from err

    claims = _leer_claims(crudos)
    # RFC 7519 §4.1.4: no se acepta "en o después" del instante `exp`.
    if ahora >= claims.expira_en:
        raise TokenExpirado(claims.session_id)
    return claims


def _leer_claims(crudos: dict[str, object]) -> Claims:
    sub, sid, rol, iat, exp = (crudos.get(c) for c in _CLAIMS_OBLIGATORIOS)
    if not isinstance(sub, str) or not sub or not isinstance(sid, str) or not sid:
        raise TokenInvalido("sub y sid deben ser cadenas no vacías")
    if not isinstance(iat, int) or not isinstance(exp, int):
        raise TokenInvalido("iat y exp deben ser enteros")
    try:
        rol_valido = Rol(str(rol))
    except ValueError as err:
        raise TokenInvalido(f"rol desconocido: {rol!r}") from err
    return Claims(
        employee_id=sub,
        session_id=sid,
        rol=rol_valido,
        emitido_en=desde_epoch(iat),
        expira_en=desde_epoch(exp),
    )
