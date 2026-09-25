from pathlib import Path
from typing import Any

from flask.testing import FlaskClient
from soporte_autenticacion import configuracion

from autenticacion.app import crear_app

CONTENCION = {"motivo": "PRUEBA", "correlation_id": "c-1", "evento_id": "e-1"}


def login(cliente: FlaskClient, usuario: str = "asesor.norte.01") -> dict[str, Any]:
    respuesta = cliente.post("/v1/sesiones", json={"usuario": usuario, "password": "solventa"})
    assert respuesta.status_code == 201, respuesta.get_json()
    cuerpo: dict[str, Any] = respuesta.get_json()
    return cuerpo


def verificar(cliente: FlaskClient, token: str) -> dict[str, Any]:
    cuerpo: dict[str, Any] = cliente.post(
        "/v1/sesiones/verificar", json={"token": token}
    ).get_json()
    return cuerpo


def test_login_emite_sesion_con_rol_de_la_base(cliente: FlaskClient) -> None:
    sesion = login(cliente)
    assert sesion["employee_id"] == "E-ASN-01"
    assert sesion["rol"] == "asesor"
    assert sesion["token"]
    assert sesion["correlation_id"]


def test_login_con_password_incorrecta_es_401_credenciales(cliente: FlaskClient) -> None:
    respuesta = cliente.post("/v1/sesiones", json={"usuario": "asesor.norte.01", "password": "x"})
    assert respuesta.status_code == 401
    assert respuesta.get_json()["type"].endswith("/credenciales")
    assert respuesta.mimetype == "application/problem+json"


def test_login_con_usuario_inexistente_es_401_credenciales(cliente: FlaskClient) -> None:
    respuesta = cliente.post("/v1/sesiones", json={"usuario": "nadie", "password": "solventa"})
    assert respuesta.status_code == 401
    assert respuesta.get_json()["type"].endswith("/credenciales")


def test_cuerpo_malformado_es_422(cliente: FlaskClient) -> None:
    respuesta = cliente.post("/v1/sesiones", json={"usuario": "asesor.norte.01"})
    assert respuesta.status_code == 422
    assert "password" in respuesta.get_json()["detail"]


def test_verificar_token_valido(cliente: FlaskClient) -> None:
    sesion = login(cliente)
    resultado = verificar(cliente, sesion["token"])
    assert resultado == {
        "correlation_id": resultado["correlation_id"],
        "valida": True,
        "employee_id": "E-ASN-01",
        "session_id": sesion["session_id"],
        "rol": "asesor",
    }


def test_verificar_token_malformado_es_invalida(cliente: FlaskClient) -> None:
    assert verificar(cliente, "no-es-un-jwt")["motivo"] == "INVALIDA"


def test_verificar_token_de_otro_secreto_es_invalida(cliente: FlaskClient, tmp_path: Path) -> None:
    otra = crear_app(configuracion(tmp_path / "otra", jwt_secret="otro-secreto"))
    with otra.test_client() as otro_cliente:
        token = login(otro_cliente)["token"]
    assert verificar(cliente, token)["motivo"] == "INVALIDA"


def test_verificar_token_expirado(tmp_path: Path) -> None:
    app = crear_app(configuracion(tmp_path, jwt_ttl_s=-10))
    with app.test_client() as cliente:
        sesion = login(cliente)
        resultado = verificar(cliente, sesion["token"])
    assert resultado["valida"] is False
    assert resultado["motivo"] == "EXPIRADA"
    assert resultado["session_id"] == sesion["session_id"]


def test_revocacion_invalida_la_sesion_y_es_idempotente(cliente: FlaskClient) -> None:
    sesion = login(cliente)
    primera = cliente.post(f"/v1/sesiones/{sesion['session_id']}/revocacion", json=CONTENCION)
    assert primera.status_code == 200
    assert primera.get_json()["ya_estaba_revocada"] is False

    resultado = verificar(cliente, sesion["token"])
    assert resultado["valida"] is False
    assert resultado["motivo"] == "REVOCADA"
    assert resultado["employee_id"] == "E-ASN-01"

    segunda = cliente.post(f"/v1/sesiones/{sesion['session_id']}/revocacion", json=CONTENCION)
    assert segunda.status_code == 200
    assert segunda.get_json()["ya_estaba_revocada"] is True
    assert segunda.get_json()["revocada_en"] == primera.get_json()["revocada_en"]


def test_revocar_sesion_inexistente_es_404(cliente: FlaskClient) -> None:
    respuesta = cliente.post("/v1/sesiones/no-existe/revocacion", json=CONTENCION)
    assert respuesta.status_code == 404
    assert respuesta.get_json()["type"].endswith("/recurso-no-encontrado")


def test_bloqueo_invalida_sesiones_vivas_e_impide_login(cliente: FlaskClient) -> None:
    sesion = login(cliente)
    respuesta = cliente.post("/v1/empleados/E-ASN-01/bloqueo", json=CONTENCION)
    assert respuesta.status_code == 200
    assert respuesta.get_json()["sesiones_afectadas"] == 1
    assert respuesta.get_json()["ya_estaba_bloqueado"] is False

    assert verificar(cliente, sesion["token"])["motivo"] == "BLOQUEADO"

    login_bloqueado = cliente.post(
        "/v1/sesiones", json={"usuario": "asesor.norte.01", "password": "solventa"}
    )
    assert login_bloqueado.status_code == 401
    assert login_bloqueado.get_json()["type"].endswith("/empleado-bloqueado")

    repetido = cliente.post("/v1/empleados/E-ASN-01/bloqueo", json=CONTENCION)
    assert repetido.get_json()["ya_estaba_bloqueado"] is True


def test_revocada_prevalece_sobre_bloqueado(cliente: FlaskClient) -> None:
    sesion = login(cliente)
    cliente.post(f"/v1/sesiones/{sesion['session_id']}/revocacion", json=CONTENCION)
    cliente.post("/v1/empleados/E-ASN-01/bloqueo", json=CONTENCION)
    assert verificar(cliente, sesion["token"])["motivo"] == "REVOCADA"


def test_alterar_rol_cambia_el_rol_de_los_logins_posteriores(cliente: FlaskClient) -> None:
    antes = login(cliente)
    respuesta = cliente.put("/v1/experimento/empleados/E-ASN-01/rol", json={"rol": "supervisor"})
    assert respuesta.status_code == 200
    assert respuesta.get_json() == {
        "correlation_id": respuesta.get_json()["correlation_id"],
        "employee_id": "E-ASN-01",
        "rol_anterior": "asesor",
        "rol": "supervisor",
    }
    # La sesión ya emitida conserva el rol con el que nació.
    assert verificar(cliente, antes["token"])["rol"] == "asesor"
    assert login(cliente)["rol"] == "supervisor"


def test_alterar_rol_desconocido_es_422(cliente: FlaskClient) -> None:
    respuesta = cliente.put("/v1/experimento/empleados/E-ASN-01/rol", json={"rol": "dios"})
    assert respuesta.status_code == 422


def test_alterar_rol_no_existe_sin_modo_experimento(tmp_path: Path) -> None:
    app = crear_app(configuracion(tmp_path, modo_experimento=False))
    with app.test_client() as cliente:
        respuesta = cliente.put(
            "/v1/experimento/empleados/E-ASN-01/rol", json={"rol": "supervisor"}
        )
    assert respuesta.status_code == 404


def test_correlation_id_entrante_se_propaga(cliente: FlaskClient) -> None:
    respuesta = cliente.get("/health", headers={"X-Correlation-Id": "abc-123"})
    assert respuesta.headers["X-Correlation-Id"] == "abc-123"
