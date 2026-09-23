from datetime import timedelta

import jwt
import pytest
from soporte_autenticacion import INICIO, SECRETO

from autenticacion import claves, tokens
from autenticacion.contracts import Rol

# --- Contraseñas --------------------------------------------------------------


def test_hash_verifica_la_contrasena_correcta_y_rechaza_otra() -> None:
    guardado = claves.hashear("solventa")
    assert claves.verificar("solventa", guardado)
    assert not claves.verificar("Solventa", guardado)
    assert not claves.verificar("", guardado)


@pytest.mark.parametrize(
    "guardado",
    ["", "solventa", "scrypt$1$2$3", "bcrypt$16384$8$1$AAAA$AAAA", "scrypt$x$8$1$AAAA$AAAA"],
)
def test_hash_con_formato_inesperado_nunca_valida(guardado: str) -> None:
    assert not claves.verificar("solventa", guardado)


def test_usuario_inexistente_paga_el_mismo_trabajo() -> None:
    # No debe lanzar ni devolver nada: solo consume el tiempo de un scrypt.
    claves.gastar_tiempo_equivalente("cualquiera")


# --- Tokens -------------------------------------------------------------------


def _emitir(rol: Rol = Rol.ASESOR, ttl_s: int = 3600) -> tuple[str, tokens.Claims]:
    return tokens.emitir(SECRETO, ttl_s, "E-ASN-01", "sid-1", rol, INICIO)


def test_emitir_y_verificar_ida_y_vuelta() -> None:
    token, emitidos = _emitir(Rol.SUPERVISOR)
    leidos = tokens.verificar(token, SECRETO, INICIO)
    assert leidos == emitidos
    assert leidos.rol is Rol.SUPERVISOR
    assert leidos.expira_en - leidos.emitido_en == timedelta(seconds=3600)


def test_expira_exactamente_en_exp() -> None:
    token, claims = _emitir(ttl_s=10)
    tokens.verificar(token, SECRETO, claims.expira_en - timedelta(microseconds=1))
    with pytest.raises(tokens.TokenExpirado) as err:
        tokens.verificar(token, SECRETO, claims.expira_en)
    assert err.value.session_id == "sid-1"


def test_un_token_expirado_con_firma_falsa_es_invalido_no_expirado() -> None:
    """La firma se comprueba antes que el tiempo: nadie obtiene un `session_id`
    de vuelta presentando un token que no firmamos."""
    falso = jwt.encode(
        {"sub": "E-ASN-01", "sid": "sid-1", "rol": "asesor", "iat": 0, "exp": 1},
        "otro-secreto-de-al-menos-32-bytes-xx",
        algorithm="HS256",
    )
    with pytest.raises(tokens.TokenInvalido):
        tokens.verificar(falso, SECRETO, INICIO)


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "E-ASN-01", "sid": "s", "rol": "gerente", "iat": 0, "exp": 2**40},
        {"sub": "", "sid": "s", "rol": "asesor", "iat": 0, "exp": 2**40},
        {"sub": "E-ASN-01", "sid": 5, "rol": "asesor", "iat": 0, "exp": 2**40},
        {"sid": "s", "rol": "asesor", "iat": 0, "exp": 2**40},
        {"sub": "E-ASN-01", "sid": "s", "iat": 0, "exp": 2**40},
        {"sub": "E-ASN-01", "sid": "s", "rol": "asesor", "exp": 2**40},
        {"sub": "E-ASN-01", "sid": "s", "rol": "asesor", "iat": 0},
    ],
)
def test_claims_invalidos_o_ausentes(claims: dict[str, object]) -> None:
    token = jwt.encode(claims, SECRETO, algorithm="HS256")
    with pytest.raises(tokens.TokenInvalido):
        tokens.verificar(token, SECRETO, INICIO)
