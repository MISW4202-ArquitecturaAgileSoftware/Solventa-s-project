import threading
import warnings
from collections.abc import Callable
from typing import Any

import jwt
import pytest
from flask import Flask
from flask.testing import FlaskClient
from soporte_autenticacion import (
    INICIO,
    SECRETO,
    TTL_S,
    RelojFalso,
    contencion,
    login,
    verificar,
)

TIPOS = "https://solventa.co/errors/"


def _problem(respuesta: Any, estado: int, tipo: str) -> dict[str, Any]:
    assert respuesta.status_code == estado
    assert respuesta.mimetype == "application/problem+json"
    cuerpo: dict[str, Any] = respuesta.get_json()
    assert cuerpo["type"] == tipo
    assert cuerpo["status"] == estado
    return cuerpo


def _claims(token: str) -> dict[str, Any]:
    claims: dict[str, Any] = jwt.decode(
        token, SECRETO, algorithms=["HS256"], options={"verify_exp": False, "verify_iat": False}
    )
    return claims


def _hs512_con_el_mismo_secreto() -> str:
    # PyJWT avisa de que el secreto es corto para HS512: es justo el token
    # ilegítimo que se quiere fabricar, así que el aviso sobra aquí.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", jwt.InsecureKeyLengthWarning)
        return jwt.encode(
            {"sub": "E-ASN-01", "sid": "s", "rol": "asesor", "iat": 0, "exp": 2**40},
            SECRETO,
            algorithm="HS512",
        )


# --- Login --------------------------------------------------------------------


def test_login_correcto_emite_token_y_registra_la_sesion(cliente: FlaskClient) -> None:
    cuerpo = login(cliente, "asesor.norte.01")

    assert cuerpo["employee_id"] == "E-ASN-01"
    assert cuerpo["rol"] == "asesor"
    assert cuerpo["expira_en"] == "2026-09-21T15:00:00Z"
    claims = _claims(cuerpo["token"])
    assert claims == {
        "sub": "E-ASN-01",
        "sid": cuerpo["session_id"],
        "rol": "asesor",
        "iat": int(INICIO.timestamp()),
        "exp": int(INICIO.timestamp()) + TTL_S,
    }


def test_login_propaga_el_correlation_id_del_gateway(cliente: FlaskClient) -> None:
    respuesta = cliente.post(
        "/v1/sesiones",
        json={"usuario": "asesor.norte.01", "password": "solventa"},
        headers={"X-Correlation-Id": "cid-del-gateway"},
    )
    assert respuesta.status_code == 201
    assert respuesta.headers["X-Correlation-Id"] == "cid-del-gateway"
    assert respuesta.get_json()["correlation_id"] == "cid-del-gateway"


def test_login_sin_correlation_id_genera_uno(cliente: FlaskClient) -> None:
    cuerpo = login(cliente, "asesor.norte.01")
    assert cuerpo["correlation_id"]
    assert cuerpo["correlation_id"] != "-"


def test_cada_login_abre_una_sesion_distinta(cliente: FlaskClient) -> None:
    uno = login(cliente, "asesor.norte.01")
    dos = login(cliente, "asesor.norte.01")
    assert uno["session_id"] != dos["session_id"]


def test_login_con_password_incorrecta_es_401_credenciales(cliente: FlaskClient) -> None:
    respuesta = cliente.post("/v1/sesiones", json={"usuario": "asesor.norte.01", "password": "x"})
    _problem(respuesta, 401, TIPOS + "credenciales")


def test_login_de_usuario_inexistente_es_indistinguible(cliente: FlaskClient) -> None:
    inexistente = cliente.post("/v1/sesiones", json={"usuario": "nadie", "password": "x"})
    incorrecta = cliente.post("/v1/sesiones", json={"usuario": "asesor.norte.01", "password": "x"})
    uno = _problem(inexistente, 401, TIPOS + "credenciales")
    dos = _problem(incorrecta, 401, TIPOS + "credenciales")
    assert uno["detail"] == dos["detail"]


def test_login_de_empleado_bloqueado_es_401_empleado_bloqueado(cliente: FlaskClient) -> None:
    cliente.post("/v1/empleados/E-ASN-01/bloqueo", json=contencion("ALCANCE_NO_AUTORIZADO"))

    respuesta = cliente.post(
        "/v1/sesiones", json={"usuario": "asesor.norte.01", "password": "solventa"}
    )
    cuerpo = _problem(respuesta, 401, TIPOS + "empleado-bloqueado")
    assert cuerpo["instance"] == "/v1/sesiones"


def test_bloqueado_con_password_incorrecta_no_revela_el_bloqueo(cliente: FlaskClient) -> None:
    cliente.post("/v1/empleados/E-ASN-01/bloqueo", json=contencion())
    respuesta = cliente.post("/v1/sesiones", json={"usuario": "asesor.norte.01", "password": "x"})
    _problem(respuesta, 401, TIPOS + "credenciales")


@pytest.mark.parametrize(
    "cuerpo",
    [
        None,
        [],
        {},
        {"usuario": "asesor.norte.01"},
        {"password": "solventa"},
        {"usuario": "", "password": "solventa"},
        {"usuario": "asesor.norte.01", "password": 123},
    ],
)
def test_login_con_cuerpo_malformado_es_422(cliente: FlaskClient, cuerpo: Any) -> None:
    respuesta = cliente.post("/v1/sesiones", json=cuerpo)
    _problem(respuesta, 422, TIPOS + "validacion")


def test_login_sin_content_type_json_es_422(cliente: FlaskClient) -> None:
    respuesta = cliente.post(
        "/v1/sesiones", data='{"usuario":"asesor.norte.01","password":"solventa"}'
    )
    _problem(respuesta, 422, TIPOS + "validacion")


def test_ni_la_password_ni_el_token_llegan_a_los_logs(
    fabrica_app: Callable[..., Flask], capsys: pytest.CaptureFixture[str]
) -> None:
    cliente = fabrica_app(log_level="DEBUG").test_client()

    token = login(cliente, "asesor.norte.01")["token"]
    verificar(cliente, token)
    cliente.post("/v1/sesiones", json={"usuario": "asesor.norte.01", "password": "p4ss-secreta"})

    salida = capsys.readouterr().out
    assert "sesion_iniciada" in salida
    assert "login_rechazado" in salida
    assert token not in salida
    assert "p4ss-secreta" not in salida
    assert '"solventa"' not in salida


# --- Verificación (§5.6) ------------------------------------------------------


def test_verificar_sesion_valida_devuelve_el_actor(cliente: FlaskClient) -> None:
    sesion = login(cliente, "asesor.norte.01")
    assert verificar(cliente, sesion["token"]) == {
        "valida": True,
        "employee_id": "E-ASN-01",
        "session_id": sesion["session_id"],
        "rol": "asesor",
    }


def test_verificar_sesion_revocada(cliente: FlaskClient) -> None:
    sesion = login(cliente, "asesor.norte.01")
    cliente.post(f"/v1/sesiones/{sesion['session_id']}/revocacion", json=contencion())

    assert verificar(cliente, sesion["token"]) == {
        "valida": False,
        "motivo": "REVOCADA",
        "session_id": sesion["session_id"],
        "employee_id": "E-ASN-01",
    }


def test_verificar_empleado_bloqueado(cliente: FlaskClient) -> None:
    sesion = login(cliente, "asesor.norte.01")
    cliente.post("/v1/empleados/E-ASN-01/bloqueo", json=contencion("ALCANCE_NO_AUTORIZADO"))

    assert verificar(cliente, sesion["token"]) == {
        "valida": False,
        "motivo": "BLOQUEADO",
        "session_id": sesion["session_id"],
        "employee_id": "E-ASN-01",
    }


def test_revocada_prevalece_sobre_bloqueado(cliente: FlaskClient) -> None:
    """§5.6 evalúa la revocación antes que el bloqueo."""
    sesion = login(cliente, "asesor.norte.01")
    cliente.post(f"/v1/sesiones/{sesion['session_id']}/revocacion", json=contencion())
    cliente.post("/v1/empleados/E-ASN-01/bloqueo", json=contencion())

    assert verificar(cliente, sesion["token"])["motivo"] == "REVOCADA"


def test_verificar_sesion_expirada(cliente: FlaskClient, reloj: RelojFalso) -> None:
    sesion = login(cliente, "asesor.norte.01")

    reloj.avanzar(TTL_S - 1)
    assert verificar(cliente, sesion["token"])["valida"] is True

    reloj.avanzar(1)
    assert verificar(cliente, sesion["token"]) == {
        "valida": False,
        "motivo": "EXPIRADA",
        "session_id": sesion["session_id"],
    }


@pytest.mark.parametrize(
    "token",
    [
        "no-es-un-jwt",
        "a.b.c",
        # Firmado con otro secreto.
        jwt.encode(
            {"sub": "E-ASN-01", "sid": "s", "rol": "asesor", "iat": 0, "exp": 2**40},
            "otro-secreto-de-al-menos-32-bytes-xx",
            algorithm="HS256",
        ),
        # Mismo secreto pero otro algoritmo: la lista de algoritmos es cerrada.
        _hs512_con_el_mismo_secreto(),
        # Sin firma (`alg: none`).
        jwt.encode(
            {"sub": "E-ASN-01", "sid": "s", "rol": "asesor", "iat": 0, "exp": 2**40},
            None,
            algorithm="none",
        ),
        # Firma válida pero sin `sid`.
        jwt.encode(
            {"sub": "E-ASN-01", "rol": "asesor", "iat": 0, "exp": 2**40},
            SECRETO,
            algorithm="HS256",
        ),
    ],
)
def test_verificar_token_malformado_es_invalida_y_nunca_401(
    cliente: FlaskClient, token: str
) -> None:
    assert verificar(cliente, token) == {"valida": False, "motivo": "INVALIDA"}


def test_verificar_token_bien_firmado_sin_sesion_es_invalida(cliente: FlaskClient) -> None:
    """P. ej. un token de una corrida anterior tras `down -v` con el mismo secreto."""
    huerfano = jwt.encode(
        {
            "sub": "E-ASN-01",
            "sid": "sesion-que-no-existe",
            "rol": "supervisor",
            "iat": int(INICIO.timestamp()),
            "exp": int(INICIO.timestamp()) + TTL_S,
        },
        SECRETO,
        algorithm="HS256",
    )
    assert verificar(cliente, huerfano) == {"valida": False, "motivo": "INVALIDA"}


def test_verificar_token_con_sub_ajeno_a_la_sesion_es_invalida(cliente: FlaskClient) -> None:
    sesion = login(cliente, "asesor.norte.01")
    ajeno = jwt.encode(
        {
            "sub": "E-SUP-01",
            "sid": sesion["session_id"],
            "rol": "supervisor",
            "iat": int(INICIO.timestamp()),
            "exp": int(INICIO.timestamp()) + TTL_S,
        },
        SECRETO,
        algorithm="HS256",
    )
    assert verificar(cliente, ajeno) == {"valida": False, "motivo": "INVALIDA"}


@pytest.mark.parametrize("cuerpo", [None, {}, {"token": ""}, {"token": 1}])
def test_verificar_con_cuerpo_malformado_es_422(cliente: FlaskClient, cuerpo: Any) -> None:
    _problem(cliente.post("/v1/sesiones/verificar", json=cuerpo), 422, TIPOS + "validacion")


# --- Revocación ---------------------------------------------------------------


def test_revocacion_es_idempotente(cliente: FlaskClient, reloj: RelojFalso) -> None:
    sid = login(cliente, "asesor.norte.01")["session_id"]

    primera = cliente.post(f"/v1/sesiones/{sid}/revocacion", json=contencion())
    assert primera.status_code == 200
    assert primera.get_json() == {
        "session_id": sid,
        "revocada_en": "2026-09-21T14:00:00Z",
        "ya_estaba_revocada": False,
    }

    reloj.avanzar(30)
    segunda = cliente.post(
        f"/v1/sesiones/{sid}/revocacion", json=contencion(evento_id="ev-2", correlation_id="c-2")
    )
    assert segunda.status_code == 200
    # Conserva el instante de la primera revocación.
    assert segunda.get_json() == {
        "session_id": sid,
        "revocada_en": "2026-09-21T14:00:00Z",
        "ya_estaba_revocada": True,
    }


def test_revocaciones_concurrentes_solo_una_gana(app: Flask) -> None:
    """Reacción puede reintentar mientras la primera llamada sigue en vuelo."""
    sid = login(app.test_client(), "asesor.norte.01")["session_id"]
    resultados: list[bool] = []
    barrera = threading.Barrier(8)

    def revocar() -> None:
        barrera.wait()
        respuesta = app.test_client().post(f"/v1/sesiones/{sid}/revocacion", json=contencion())
        resultados.append(respuesta.get_json()["ya_estaba_revocada"])

    hilos = [threading.Thread(target=revocar) for _ in range(8)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert sorted(resultados) == [False] + [True] * 7


def test_revocacion_fija_el_correlation_id_del_evento(cliente: FlaskClient) -> None:
    sid = login(cliente, "asesor.norte.01")["session_id"]
    respuesta = cliente.post(
        f"/v1/sesiones/{sid}/revocacion", json=contencion(correlation_id="cid-del-incidente")
    )
    assert respuesta.headers["X-Correlation-Id"] == "cid-del-incidente"


def test_revocar_sesion_inexistente_es_404(cliente: FlaskClient) -> None:
    respuesta = cliente.post("/v1/sesiones/no-existe/revocacion", json=contencion())
    _problem(respuesta, 404, TIPOS + "recurso-no-encontrado")


@pytest.mark.parametrize("falta", ["motivo", "correlation_id", "evento_id"])
def test_revocacion_con_cuerpo_incompleto_es_422(cliente: FlaskClient, falta: str) -> None:
    sid = login(cliente, "asesor.norte.01")["session_id"]
    cuerpo = contencion()
    del cuerpo[falta]
    _problem(cliente.post(f"/v1/sesiones/{sid}/revocacion", json=cuerpo), 422, TIPOS + "validacion")


def test_revocar_una_sesion_no_afecta_a_otra_del_mismo_empleado(cliente: FlaskClient) -> None:
    uno = login(cliente, "asesor.norte.01")
    dos = login(cliente, "asesor.norte.01")
    cliente.post(f"/v1/sesiones/{uno['session_id']}/revocacion", json=contencion())

    assert verificar(cliente, uno["token"])["motivo"] == "REVOCADA"
    assert verificar(cliente, dos["token"])["valida"] is True


# --- Bloqueo ------------------------------------------------------------------


def test_bloqueo_invalida_todas_las_sesiones_vivas(cliente: FlaskClient) -> None:
    uno = login(cliente, "asesor.norte.01")
    dos = login(cliente, "asesor.norte.01")
    otro_empleado = login(cliente, "asesor.norte.02")

    respuesta = cliente.post("/v1/empleados/E-ASN-01/bloqueo", json=contencion())
    assert respuesta.status_code == 200
    assert respuesta.get_json() == {
        "employee_id": "E-ASN-01",
        "bloqueado_en": "2026-09-21T14:00:00Z",
        "ya_estaba_bloqueado": False,
        "sesiones_afectadas": 2,
    }
    assert verificar(cliente, uno["token"])["motivo"] == "BLOQUEADO"
    assert verificar(cliente, dos["token"])["motivo"] == "BLOQUEADO"
    assert verificar(cliente, otro_empleado["token"])["valida"] is True


def test_bloqueo_no_cuenta_sesiones_revocadas_ni_expiradas(
    cliente: FlaskClient, reloj: RelojFalso
) -> None:
    vieja = login(cliente, "asesor.norte.01")
    reloj.avanzar(TTL_S)  # `vieja` expira justo ahora
    revocada = login(cliente, "asesor.norte.01")
    cliente.post(f"/v1/sesiones/{revocada['session_id']}/revocacion", json=contencion())
    login(cliente, "asesor.norte.01")  # la única viva

    respuesta = cliente.post("/v1/empleados/E-ASN-01/bloqueo", json=contencion())
    assert respuesta.get_json()["sesiones_afectadas"] == 1
    assert verificar(cliente, vieja["token"])["motivo"] == "EXPIRADA"


def test_bloqueo_es_idempotente(cliente: FlaskClient, reloj: RelojFalso) -> None:
    login(cliente, "asesor.norte.01")
    cliente.post("/v1/empleados/E-ASN-01/bloqueo", json=contencion())
    reloj.avanzar(30)

    segunda = cliente.post("/v1/empleados/E-ASN-01/bloqueo", json=contencion(evento_id="ev-2"))
    assert segunda.status_code == 200
    assert segunda.get_json() == {
        "employee_id": "E-ASN-01",
        "bloqueado_en": "2026-09-21T14:00:00Z",
        "ya_estaba_bloqueado": True,
        "sesiones_afectadas": 0,
    }


def test_bloquear_empleado_inexistente_es_404(cliente: FlaskClient) -> None:
    respuesta = cliente.post("/v1/empleados/E-NADIE/bloqueo", json=contencion())
    _problem(respuesta, 404, TIPOS + "recurso-no-encontrado")


def test_bloqueo_con_cuerpo_malformado_es_422(cliente: FlaskClient) -> None:
    respuesta = cliente.post("/v1/empleados/E-ASN-01/bloqueo", json={"motivo": "X"})
    _problem(respuesta, 422, TIPOS + "validacion")


# --- Experimento: alteración de rol -------------------------------------------


def test_alterar_rol_cambia_solo_el_rol_del_empleado(cliente: FlaskClient) -> None:
    anterior = login(cliente, "asesor.norte.01")

    respuesta = cliente.put("/v1/experimento/empleados/E-ASN-01/rol", json={"rol": "supervisor"})
    assert respuesta.status_code == 200
    assert respuesta.get_json() == {
        "employee_id": "E-ASN-01",
        "rol_anterior": "asesor",
        "rol": "supervisor",
    }

    # La sesión vieja conserva el rol con el que nació (§3.3)…
    assert verificar(cliente, anterior["token"])["rol"] == "asesor"
    # …y hace falta un login nuevo para que el token refleje la alteración.
    nueva = login(cliente, "asesor.norte.01")
    assert nueva["rol"] == "supervisor"
    assert verificar(cliente, nueva["token"])["rol"] == "supervisor"


def test_alterar_rol_de_empleado_inexistente_es_404(cliente: FlaskClient) -> None:
    respuesta = cliente.put("/v1/experimento/empleados/E-NADIE/rol", json={"rol": "supervisor"})
    _problem(respuesta, 404, TIPOS + "recurso-no-encontrado")


@pytest.mark.parametrize("cuerpo", [{}, {"rol": "administrador"}, {"rol": 1}])
def test_alterar_rol_con_cuerpo_invalido_es_422(cliente: FlaskClient, cuerpo: Any) -> None:
    respuesta = cliente.put("/v1/experimento/empleados/E-ASN-01/rol", json=cuerpo)
    _problem(respuesta, 422, TIPOS + "validacion")


def test_sin_modo_experimento_la_ruta_de_rol_no_existe(
    fabrica_app: Callable[..., Flask],
) -> None:
    cliente = fabrica_app(modo_experimento=False).test_client()

    respuesta = cliente.put("/v1/experimento/empleados/E-ASN-01/rol", json={"rol": "supervisor"})
    _problem(respuesta, 404, "about:blank")
    assert login(cliente, "asesor.norte.01")["rol"] == "asesor"


# --- Errores HTTP genéricos y salud -------------------------------------------


def test_ruta_inexistente_es_problem_json(cliente: FlaskClient) -> None:
    cuerpo = _problem(cliente.get("/no-existe"), 404, "about:blank")
    assert cuerpo["instance"] == "/no-existe"


def test_metodo_no_admitido_es_problem_json(cliente: FlaskClient) -> None:
    _problem(cliente.get("/v1/sesiones"), 405, "about:blank")


def test_health(cliente: FlaskClient) -> None:
    respuesta = cliente.get("/health")
    assert respuesta.status_code == 200
    assert respuesta.get_json() == {"estado": "ok"}


# --- Validación de fase F2 (el guion del plan, en proceso) --------------------


def test_guion_de_validacion_f2(cliente: FlaskClient) -> None:
    token = login(cliente, "asesor.norte.01")["token"]
    primera = verificar(cliente, token)
    assert primera["valida"] is True
    assert primera["rol"] == "asesor"

    sid = jwt.decode(token, options={"verify_signature": False})["sid"]
    revocacion = cliente.post(
        f"/v1/sesiones/{sid}/revocacion",
        json={"motivo": "PRUEBA", "correlation_id": "x", "evento_id": "x"},
    )
    assert revocacion.status_code == 200

    assert verificar(cliente, token)["motivo"] == "REVOCADA"

    alteracion = cliente.put("/v1/experimento/empleados/E-ASN-01/rol", json={"rol": "supervisor"})
    assert alteracion.get_json()["rol_anterior"] == "asesor"
    assert alteracion.get_json()["rol"] == "supervisor"
