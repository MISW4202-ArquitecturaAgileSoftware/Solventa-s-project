from typing import Any

import pytest
from flask.testing import FlaskClient
from soporte_api_gateway import URL_AUTENTICACION, URL_VALIDACION, ClienteHttpDoble, ok

from api_gateway.errors import ErrorUpstream
from api_gateway.http import RespuestaInterna

VERIFICAR = f"{URL_AUTENTICACION}/v1/sesiones/verificar"
LOGIN = f"{URL_AUTENTICACION}/v1/sesiones"
OPERACIONES = f"{URL_VALIDACION}/v1/operaciones"
OTP = f"{URL_VALIDACION}/v1/otp"

BEARER = {"Authorization": "Bearer eyJ-token-de-prueba"}


def _valida(
    employee_id: str = "E-ASN-01", session_id: str = "s1", rol: str = "asesor"
) -> dict[str, Any]:
    return {"valida": True, "employee_id": employee_id, "session_id": session_id, "rol": rol}


def _invalida(motivo: str, **extra: str) -> dict[str, Any]:
    return {"valida": False, "motivo": motivo, **extra}


# --- Autenticación del Bearer -------------------------------------------------


def test_sin_authorization_es_401_sesion_invalida_sin_llamar_a_autenticacion(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    respuesta = cliente.get("/v1/polizas/POL-SUR-003")
    assert respuesta.status_code == 401
    assert respuesta.get_json()["type"].endswith("/sesion-invalida")
    assert respuesta.mimetype == "application/problem+json"
    assert http.llamadas == []


def test_bearer_malformado_es_401_sin_llamar_a_autenticacion(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    respuesta = cliente.get("/v1/polizas/POL-SUR-003", headers={"Authorization": "Token xyz"})
    assert respuesta.status_code == 401
    assert respuesta.get_json()["type"].endswith("/sesion-invalida")
    assert http.llamadas == []


def test_verificacion_revocada_es_401_sesion_revocada(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(VERIFICAR, ok(_invalida("REVOCADA", session_id="s1", employee_id="E-ASN-01")))
    respuesta = cliente.get("/v1/polizas/POL-SUR-003", headers=BEARER)
    assert respuesta.status_code == 401
    cuerpo = respuesta.get_json()
    assert cuerpo["type"].endswith("/sesion-revocada")
    assert "s1" in cuerpo["detail"]
    assert respuesta.mimetype == "application/problem+json"


def test_verificacion_bloqueado_es_401_empleado_bloqueado(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(VERIFICAR, ok(_invalida("BLOQUEADO", session_id="s1", employee_id="E-ASN-01")))
    respuesta = cliente.get("/v1/polizas/POL-SUR-003", headers=BEARER)
    assert respuesta.status_code == 401
    assert respuesta.get_json()["type"].endswith("/empleado-bloqueado")


def test_verificacion_expirada_es_401_sesion_invalida(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(VERIFICAR, ok(_invalida("EXPIRADA", session_id="s1")))
    respuesta = cliente.get("/v1/polizas/POL-SUR-003", headers=BEARER)
    assert respuesta.status_code == 401
    assert respuesta.get_json()["type"].endswith("/sesion-invalida")


def test_verificacion_indefinida_es_401_sesion_invalida(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(VERIFICAR, ok(_invalida("INVALIDA")))
    respuesta = cliente.get("/v1/polizas/POL-SUR-003", headers=BEARER)
    assert respuesta.status_code == 401
    assert respuesta.get_json()["type"].endswith("/sesion-invalida")


# --- Reenvío a Validación con el actor resuelto ------------------------------


def test_consulta_poliza_reenvia_el_actor_y_propaga_200_con_cuerpo_integro(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(VERIFICAR, ok(_valida(rol="asesor")))
    resultado = {"poliza_id": "POL-SUR-003", "region": "sur", "estado": "PENDIENTE"}
    http.cuando(OPERACIONES, ok({"estado": "OK", "resultado": resultado}))

    respuesta = cliente.get("/v1/polizas/POL-SUR-003", headers=BEARER)

    assert respuesta.status_code == 200
    assert respuesta.get_json()["resultado"] == resultado

    url, payload, cid = http.llamadas[-1]
    assert url == OPERACIONES
    assert payload["correlation_id"] == cid
    assert payload["actor"] == {"employee_id": "E-ASN-01", "session_id": "s1", "rol": "asesor"}
    assert payload["operacion"] == "consultar_poliza"
    assert payload["parametros"] == {"poliza_id": "POL-SUR-003"}


def test_aprobacion_usa_la_operacion_aprobar_poliza(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(VERIFICAR, ok(_valida(rol="supervisor")))
    http.cuando(OPERACIONES, ok({"estado": "OK", "resultado": {"estado": "APROBADA"}}))

    respuesta = cliente.post("/v1/polizas/POL-NOR-001/aprobacion", headers=BEARER)

    assert respuesta.status_code == 200
    _, payload, _ = http.llamadas[-1]
    assert payload["operacion"] == "aprobar_poliza"
    assert payload["parametros"] == {"poliza_id": "POL-NOR-001"}


def test_cotizaciones_reenvia_el_cuerpo_como_parametros(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(VERIFICAR, ok(_valida()))
    http.cuando(OPERACIONES, ok({"estado": "OK", "resultado": {}}))
    cuerpo = {"producto": "vida_hipotecario", "moneda": "COP", "suma_asegurada": "1000"}

    respuesta = cliente.post("/v1/cotizaciones", json=cuerpo, headers=BEARER)

    assert respuesta.status_code == 200
    _, payload, _ = http.llamadas[-1]
    assert payload["operacion"] == "cotizar"
    assert payload["parametros"] == cuerpo


def test_cotizaciones_sin_cuerpo_objeto_es_422_sin_llamar_a_validacion(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(VERIFICAR, ok(_valida()))

    respuesta = cliente.post("/v1/cotizaciones", json=[1, 2, 3], headers=BEARER)

    assert respuesta.status_code == 422
    assert respuesta.get_json()["type"].endswith("/validacion")
    assert all(url != OPERACIONES for url, _, _ in http.llamadas)


def test_otp_envia_el_session_id_resuelto_por_la_verificacion(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(VERIFICAR, ok(_valida(session_id="s-de-la-sesion")))
    http.cuando(OTP, ok({"estado": "OK", "operacion": {}}))

    respuesta = cliente.post("/v1/otp", json={"codigo": "482913"}, headers=BEARER)

    assert respuesta.status_code == 200
    url, payload, cid = http.llamadas[-1]
    assert url == OTP
    assert payload == {"correlation_id": cid, "session_id": "s-de-la-sesion", "codigo": "482913"}


# --- Login: reenvío tal cual --------------------------------------------------


def test_login_reenvia_el_cuerpo_tal_cual_y_propaga_201(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    cuerpo = {"usuario": "asesor.norte.01", "password": "solventa"}
    http.cuando(LOGIN, ok({"token": "eyJ", "session_id": "s1"}, estado=201))

    respuesta = cliente.post("/v1/sesiones", json=cuerpo)

    assert respuesta.status_code == 201
    url, payload, _ = http.llamadas[-1]
    assert url == LOGIN
    assert payload == cuerpo


def test_login_no_requiere_bearer(cliente: FlaskClient, http: ClienteHttpDoble) -> None:
    http.cuando(LOGIN, ok({"token": "eyJ"}, estado=201))
    respuesta = cliente.post("/v1/sesiones", json={"usuario": "x", "password": "y"})
    assert respuesta.status_code == 201


def test_login_401_se_propaga_con_su_content_type(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(
        LOGIN,
        RespuestaInterna(
            estado=401,
            cuerpo={"type": "https://solventa.co/errors/credenciales", "status": 401},
            content_type="application/problem+json",
        ),
    )
    respuesta = cliente.post("/v1/sesiones", json={"usuario": "x", "password": "y"})
    assert respuesta.status_code == 401
    assert respuesta.mimetype == "application/problem+json"
    assert respuesta.get_json()["type"].endswith("/credenciales")


# --- Propagación tal cual de estados y Content-Type --------------------------


@pytest.mark.parametrize(
    ("estado", "content_type"),
    [
        (202, "application/json"),
        (403, "application/problem+json"),
        (409, "application/problem+json"),
        (504, "application/problem+json"),
    ],
)
def test_propaga_estado_y_content_type_de_validacion_tal_cual(
    cliente: FlaskClient, http: ClienteHttpDoble, estado: int, content_type: str
) -> None:
    http.cuando(VERIFICAR, ok(_valida()))
    http.cuando(
        OPERACIONES,
        RespuestaInterna(estado=estado, cuerpo={"status": estado}, content_type=content_type),
    )

    respuesta = cliente.get("/v1/polizas/POL-SUR-003", headers=BEARER)

    assert respuesta.status_code == estado
    assert respuesta.mimetype == content_type
    assert respuesta.get_json() == {"status": estado}


# --- Traducción de fallos del cliente HTTP a upstream ------------------------


def test_timeout_de_autenticacion_es_504_upstream(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(VERIFICAR, ErrorUpstream("no respondió a tiempo", 504))
    respuesta = cliente.get("/v1/polizas/POL-SUR-003", headers=BEARER)
    assert respuesta.status_code == 504
    assert respuesta.get_json()["type"].endswith("/upstream")
    assert respuesta.mimetype == "application/problem+json"


def test_conexion_rechazada_de_validacion_es_503_upstream(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(VERIFICAR, ok(_valida()))
    http.cuando(OPERACIONES, ErrorUpstream("rechazó la conexión", 503))
    respuesta = cliente.get("/v1/polizas/POL-SUR-003", headers=BEARER)
    assert respuesta.status_code == 503
    assert respuesta.get_json()["type"].endswith("/upstream")


def test_cuerpo_no_json_de_validacion_es_502_upstream(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(VERIFICAR, ok(_valida()))
    http.cuando(OPERACIONES, ErrorUpstream("respondió un cuerpo no JSON", 502))
    respuesta = cliente.get("/v1/polizas/POL-SUR-003", headers=BEARER)
    assert respuesta.status_code == 502
    assert respuesta.get_json()["type"].endswith("/upstream")


# --- Correlation-Id ------------------------------------------------------------


def test_x_correlation_id_presente_y_coincide_con_la_enviada_a_los_servicios_internos(
    cliente: FlaskClient, http: ClienteHttpDoble
) -> None:
    http.cuando(VERIFICAR, ok(_valida()))
    http.cuando(OPERACIONES, ok({"estado": "OK", "resultado": {}}))

    respuesta = cliente.get("/v1/polizas/POL-SUR-003", headers=BEARER)

    cid_respuesta = respuesta.headers["X-Correlation-Id"]
    assert cid_respuesta

    for _url, payload, cid_llamada in http.llamadas:
        assert cid_llamada == cid_respuesta
        if isinstance(payload, dict) and "correlation_id" in payload:
            assert payload["correlation_id"] == cid_respuesta


def test_x_correlation_id_presente_en_401_sin_llamadas_internas(cliente: FlaskClient) -> None:
    respuesta = cliente.get("/v1/polizas/POL-SUR-003")
    assert respuesta.headers["X-Correlation-Id"]


def test_x_correlation_id_presente_en_health(cliente: FlaskClient) -> None:
    respuesta = cliente.get("/health")
    assert respuesta.status_code == 200
    assert respuesta.headers["X-Correlation-Id"]
