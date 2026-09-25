"""Emisión y verificación de JWT (HS256).

Solo Autenticación conoce el secreto. El gateway no interpreta el token: lo
envía aquí a verificar, porque la revocación solo se conoce en esta base.
"""

from dataclasses import dataclass
from datetime import datetime

import jwt

from autenticacion.contracts import Rol

_ALGORITMO = "HS256"


class ErrorToken(Exception):
    pass


class ErrorTokenInvalido(ErrorToken):
    pass


class ErrorTokenExpirado(ErrorToken):
    def __init__(self, session_id: str | None) -> None:
        super().__init__("token expirado")
        self.session_id = session_id


@dataclass(frozen=True, slots=True)
class Claims:
    employee_id: str
    session_id: str
    rol: Rol


def emitir(
    secreto: str,
    employee_id: str,
    session_id: str,
    rol: Rol,
    emitido_en: datetime,
    expira_en: datetime,
) -> str:
    return jwt.encode(
        {
            "sub": employee_id,
            "sid": session_id,
            "rol": rol.value,
            "iat": int(emitido_en.timestamp()),
            "exp": int(expira_en.timestamp()),
        },
        secreto,
        algorithm=_ALGORITMO,
    )


def decodificar(secreto: str, token: str) -> Claims:
    try:
        crudo = jwt.decode(token, secreto, algorithms=[_ALGORITMO])
    except jwt.ExpiredSignatureError as err:
        # La firma es válida: se pueden leer los claims para reportar qué sesión
        # expiró, aunque ya no sirva.
        sin_exp = jwt.decode(token, secreto, algorithms=[_ALGORITMO], options={"verify_exp": False})
        sid = sin_exp.get("sid")
        raise ErrorTokenExpirado(sid if isinstance(sid, str) else None) from err
    except jwt.InvalidTokenError as err:
        raise ErrorTokenInvalido(str(err)) from err

    sub, sid, rol = crudo.get("sub"), crudo.get("sid"), crudo.get("rol")
    if not isinstance(sub, str) or not isinstance(sid, str) or not isinstance(rol, str):
        raise ErrorTokenInvalido("claims incompletos")
    try:
        return Claims(employee_id=sub, session_id=sid, rol=Rol(rol))
    except ValueError as err:
        raise ErrorTokenInvalido("rol desconocido") from err
