import json
from pathlib import Path
from typing import Any

import pytest
from fake_redis import RedisFalso
from flask import Flask
from flask.testing import FlaskClient
from soporte_validacion import configuracion

from validacion.app import crear_app
from validacion.repositorio import Repositorio


def _operacion(
    correlation_id: str,
    employee_id: str,
    session_id: str,
    rol: str,
    operacion: str,
    parametros: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "correlation_id": correlation_id,
        "actor": {"employee_id": employee_id, "session_id": session_id, "rol": rol},
        "operacion": operacion,
        "parametros": parametros or {"poliza_id": "POL-NOR-001"},
    }


def _respuesta_worker(
    correlation_id: str,
    codigo: str = "OK",
    resultado: dict[str, Any] | None = None,
    error: str | None = None,
    servicio: str = "gestion-polizas",
) -> str:
    return json.dumps(
        {
            "correlation_id": correlation_id,
            "tipo": "operacion.resuelta",
            "servicio": servicio,
            "estado": "OK" if codigo == "OK" else "ERROR",
            "codigo": codigo,
            "duracion_ms": 4,
            "resultado": resultado,
            "error": error,
        }
    )


def _precargar_respuesta(redis_falso: RedisFalso, correlation_id: str, **kwargs: Any) -> None:
    redis_falso.lpush(f"resp:{correlation_id}", _respuesta_worker(correlation_id, **kwargs))


def _repositorio(app: Flask) -> Repositorio:
    repositorio: Repositorio = app.extensions["repositorio"]
    return repositorio


def _entrada_stream(redis_falso: RedisFalso, stream: str, indice: int = 0) -> dict[str, Any]:
    entrada: dict[str, Any] = json.loads(redis_falso.streams[stream][indice]["data"])
    return entrada


def test_health(cliente: FlaskClient) -> None:
    assert cliente.get("/health").status_code == 200


def test_rol_permitido_despacha_y_publica_el_sobre_correcto(
    cliente: FlaskClient, redis_falso: RedisFalso
) -> None:
    resultado_worker = {"poliza_id": "POL-NOR-001", "region": "norte", "estado": "PENDIENTE"}
    _precargar_respuesta(redis_falso, "c1", resultado=resultado_worker)

    cuerpo = _operacion("c1", "E-ASN-01", "s1", "asesor", "consultar_poliza")
    respuesta = cliente.post("/v1/operaciones", json=cuerpo)

    assert respuesta.status_code == 200, respuesta.get_json()
    datos = respuesta.get_json()
    assert datos == {"correlation_id": "c1", "estado": "OK", "resultado": resultado_worker}
    assert respuesta.headers["X-Correlation-Id"] == "c1"

    assert len(redis_falso.streams["sol:polizas"]) == 1
    sobre = _entrada_stream(redis_falso, "sol:polizas")
    assert sobre["correlation_id"] == "c1"
    assert sobre["actor"] == {"employee_id": "E-ASN-01", "session_id": "s1", "rol": "asesor"}
    assert sobre["operacion"] == "consultar_poliza"
    assert sobre["parametros"] == {"poliza_id": "POL-NOR-001"}
    assert "fecha_calculo" not in sobre
    # BLPOP consumió la respuesta y DEL la limpió.
    assert redis_falso.listas.get("resp:c1") in (None, [])


def test_cotizar_agrega_fecha_calculo_en_el_sobre(
    cliente: FlaskClient, redis_falso: RedisFalso
) -> None:
    _precargar_respuesta(redis_falso, "c-cot", resultado={"cotizacion": {}, "explicacion": {}})
    cuerpo = _operacion(
        "c-cot",
        "E-ASN-01",
        "s1",
        "asesor",
        "cotizar",
        parametros={"producto": "vida_hipotecario"},
    )
    respuesta = cliente.post("/v1/operaciones", json=cuerpo)

    assert respuesta.status_code == 200, respuesta.get_json()
    assert len(redis_falso.streams["sol:cotizador"]) == 1
    sobre = _entrada_stream(redis_falso, "sol:cotizador")
    assert sobre["fecha_calculo"]
    assert len(sobre["fecha_calculo"]) == len("2026-09-21")


def test_asesor_no_autorizado_para_aprobar_poliza_es_403(
    cliente: FlaskClient, redis_falso: RedisFalso
) -> None:
    cuerpo = _operacion("c2", "E-ASN-01", "s1", "asesor", "aprobar_poliza")
    respuesta = cliente.post("/v1/operaciones", json=cuerpo)

    assert respuesta.status_code == 403
    assert respuesta.get_json()["type"].endswith("/operacion-no-autorizada")
    assert redis_falso.streams["sol:polizas"] == []
    assert redis_falso.streams["sol:cotizador"] == []


def test_operacion_empleado_desconocido_es_403_operacion_no_autorizada(
    cliente: FlaskClient,
) -> None:
    cuerpo = _operacion("c-x", "E-NO-EXISTE", "s1", "asesor", "consultar_poliza")
    respuesta = cliente.post("/v1/operaciones", json=cuerpo)

    assert respuesta.status_code == 403
    assert respuesta.get_json()["type"].endswith("/operacion-no-autorizada")


def test_operacion_desconocida_es_422(cliente: FlaskClient) -> None:
    cuerpo = _operacion("c-y", "E-ASN-01", "s1", "asesor", "volar")
    respuesta = cliente.post("/v1/operaciones", json=cuerpo)

    assert respuesta.status_code == 422
    assert respuesta.get_json()["type"].endswith("/validacion")


def test_rol_declarado_distinto_al_observado_retiene_con_otp(
    cliente: FlaskClient, redis_falso: RedisFalso, app: Flask
) -> None:
    cuerpo = _operacion("c3", "E-ASN-01", "s1", "supervisor", "aprobar_poliza")
    respuesta = cliente.post("/v1/operaciones", json=cuerpo)

    assert respuesta.status_code == 202, respuesta.get_json()
    datos = respuesta.get_json()
    assert datos["correlation_id"] == "c3"
    assert datos["estado"] == "OTP_REQUERIDO"
    assert datos["session_id"] == "s1"
    assert datos["operacion"] == "aprobar_poliza"
    assert datos["detalle"]

    assert redis_falso.streams["sol:polizas"] == []
    assert redis_falso.streams["sol:cotizador"] == []

    pendiente = _repositorio(app).otp_pendiente("s1")
    assert pendiente is not None
    assert pendiente.correlation_id == "c3"
    assert pendiente.sobre.actor.rol.value == "supervisor"
    assert pendiente.sobre.operacion.value == "aprobar_poliza"
    assert pendiente.sobre.parametros == {"poliza_id": "POL-NOR-001"}


def test_segundo_intento_con_pendiente_es_409(cliente: FlaskClient) -> None:
    primero = _operacion("c3", "E-ASN-01", "s1", "supervisor", "aprobar_poliza")
    assert cliente.post("/v1/operaciones", json=primero).status_code == 202

    segundo = _operacion("c3b", "E-ASN-01", "s1", "supervisor", "aprobar_poliza")
    respuesta = cliente.post("/v1/operaciones", json=segundo)

    assert respuesta.status_code == 409
    assert respuesta.get_json()["type"].endswith("/otp-pendiente")


def test_otp_correcto_actualiza_rol_y_despacha_el_sobre_retenido(
    cliente: FlaskClient, redis_falso: RedisFalso
) -> None:
    retenida = _operacion("c-op", "E-ASN-01", "s1", "supervisor", "aprobar_poliza")
    assert cliente.post("/v1/operaciones", json=retenida).status_code == 202

    codigo = cliente.get("/v1/experimento/otp/s1").get_json()["codigo"]
    resultado_worker = {
        "poliza_id": "POL-NOR-001",
        "estado": "APROBADA",
        "aprobada_por": "E-ASN-01",
        "aprobada_en": "2026-09-21T14:02:11Z",
    }
    _precargar_respuesta(redis_falso, "c-op", resultado=resultado_worker)

    respuesta = cliente.post(
        "/v1/otp", json={"correlation_id": "c-otp-1", "session_id": "s1", "codigo": codigo}
    )

    assert respuesta.status_code == 200, respuesta.get_json()
    datos = respuesta.get_json()
    assert datos["correlation_id"] == "c-otp-1"
    assert datos["estado"] == "OK"
    assert datos["operacion"] == {
        "correlation_id": "c-op",
        "operacion": "aprobar_poliza",
        "resultado": resultado_worker,
    }
    assert len(redis_falso.streams["sol:polizas"]) == 1

    # Ya no hay pendiente y una operación nueva con el mismo rol no pide OTP.
    assert cliente.get("/v1/experimento/otp/s1").status_code == 404

    _precargar_respuesta(redis_falso, "c-op2", resultado={"poliza_id": "POL-NOR-002"})
    siguiente = _operacion(
        "c-op2",
        "E-ASN-01",
        "s1",
        "supervisor",
        "consultar_poliza",
        parametros={"poliza_id": "POL-NOR-002"},
    )
    respuesta2 = cliente.post("/v1/operaciones", json=siguiente)
    assert respuesta2.status_code == 200, respuesta2.get_json()


def test_otp_incorrecto_revoca_y_publica_evento_de_seguridad(
    cliente: FlaskClient,
    redis_falso: RedisFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("validacion.otp.generar_codigo", lambda: "123456")

    retenida = _operacion("c-op2", "E-ASN-01", "s1", "supervisor", "aprobar_poliza")
    assert cliente.post("/v1/operaciones", json=retenida).status_code == 202

    respuesta = cliente.post(
        "/v1/otp", json={"correlation_id": "c-otp-2", "session_id": "s1", "codigo": "000000"}
    )

    assert respuesta.status_code == 403
    assert respuesta.get_json()["type"].endswith("/otp-fallido")

    assert cliente.get("/v1/experimento/otp/s1").status_code == 404
    assert redis_falso.streams["sol:polizas"] == []

    assert len(redis_falso.streams["seguridad"]) == 1
    evento = _entrada_stream(redis_falso, "seguridad")
    assert evento["motivo"] == "OTP_FALLIDO"
    assert evento["accion"] == "REVOCAR"
    assert evento["employee_id"] == "E-ASN-01"
    assert evento["session_id"] == "s1"
    assert evento["detalle"] == {"operacion": "aprobar_poliza", "poliza_id": "POL-NOR-001"}


def test_otp_sin_pendiente_es_404(cliente: FlaskClient) -> None:
    respuesta = cliente.post(
        "/v1/otp", json={"correlation_id": "c-x", "session_id": "sin-sesion", "codigo": "000000"}
    )
    assert respuesta.status_code == 404
    assert respuesta.get_json()["type"].endswith("/sin-otp-pendiente")


def test_anomalia_fuera_de_alcance_revoca(cliente: FlaskClient, redis_falso: RedisFalso) -> None:
    cuerpo = {
        "evento_id": "e1",
        "correlation_id": "c5",
        "employee_id": "E-ASN-01",
        "session_id": "s1",
        "accion": "CONSULTA_POLIZA",
        "region_consultada": "sur",
    }
    respuesta = cliente.post("/v1/anomalias", json=cuerpo)

    assert respuesta.status_code == 202
    assert respuesta.get_json() == {"evento_id": "e1", "decision": "REVOCAR"}

    evento = _entrada_stream(redis_falso, "seguridad")
    assert evento["motivo"] == "ALCANCE_NO_AUTORIZADO"
    assert evento["accion"] == "REVOCAR"
    assert evento["detalle"] == {
        "accion": "CONSULTA_POLIZA",
        "region_consultada": "sur",
        "alcance_autorizado": ["norte"],
        "evento_auditoria_id": "e1",
    }


def test_anomalia_dentro_de_alcance_alerta(cliente: FlaskClient, redis_falso: RedisFalso) -> None:
    cuerpo = {
        "evento_id": "e2",
        "correlation_id": "c6",
        "employee_id": "E-ASM-01",
        "session_id": "s2",
        "accion": "CONSULTA_POLIZA",
        "region_consultada": "centro",
    }
    respuesta = cliente.post("/v1/anomalias", json=cuerpo)

    assert respuesta.status_code == 202
    assert respuesta.get_json() == {"evento_id": "e2", "decision": "ALERTAR"}

    evento = _entrada_stream(redis_falso, "seguridad")
    assert evento["motivo"] == "CONSULTA_INUSUAL"
    assert evento["accion"] == "ALERTAR"


def test_anomalia_empleado_desconocido_es_404(cliente: FlaskClient) -> None:
    cuerpo = {
        "evento_id": "e3",
        "correlation_id": "c7",
        "employee_id": "E-NO-EXISTE",
        "session_id": "s3",
        "accion": "CONSULTA_POLIZA",
        "region_consultada": "sur",
    }
    respuesta = cliente.post("/v1/anomalias", json=cuerpo)

    assert respuesta.status_code == 404
    assert respuesta.get_json()["type"].endswith("/recurso-no-encontrado")


def test_timeout_sin_respuesta_es_504(cliente: FlaskClient, redis_falso: RedisFalso) -> None:
    cuerpo = _operacion("c-timeout", "E-ASN-01", "s1", "asesor", "consultar_poliza")
    respuesta = cliente.post("/v1/operaciones", json=cuerpo)

    assert respuesta.status_code == 504
    assert respuesta.get_json()["type"].endswith("/timeout-operacion")


def test_traduccion_no_encontrada_es_404(cliente: FlaskClient, redis_falso: RedisFalso) -> None:
    _precargar_respuesta(redis_falso, "c-404", codigo="NO_ENCONTRADA", error="poliza no existe")
    cuerpo = _operacion(
        "c-404", "E-ASN-01", "s1", "asesor", "consultar_poliza", {"poliza_id": "POL-XXX-999"}
    )
    respuesta = cliente.post("/v1/operaciones", json=cuerpo)

    assert respuesta.status_code == 404
    assert respuesta.get_json()["type"].endswith("/recurso-no-encontrado")
    assert respuesta.get_json()["detail"] == "poliza no existe"


def test_traduccion_estado_invalido_es_409(cliente: FlaskClient, redis_falso: RedisFalso) -> None:
    _precargar_respuesta(
        redis_falso, "c-409", codigo="ESTADO_INVALIDO", error="la póliza no está PENDIENTE"
    )
    cuerpo = _operacion("c-409", "E-SUP-01", "sX", "supervisor", "aprobar_poliza")
    respuesta = cliente.post("/v1/operaciones", json=cuerpo)

    assert respuesta.status_code == 409
    assert respuesta.get_json()["type"].endswith("/estado-invalido")


def test_traduccion_validacion_del_worker_es_422(
    cliente: FlaskClient, redis_falso: RedisFalso
) -> None:
    _precargar_respuesta(
        redis_falso, "c-422", codigo="VALIDACION", error="suma_asegurada fuera de rango"
    )
    cuerpo = _operacion(
        "c-422", "E-ASN-01", "s1", "asesor", "cotizar", {"producto": "vida_hipotecario"}
    )
    respuesta = cliente.post("/v1/operaciones", json=cuerpo)

    assert respuesta.status_code == 422
    assert respuesta.get_json()["type"].endswith("/validacion")
    assert respuesta.get_json()["detail"] == "suma_asegurada fuera de rango"


def test_traduccion_interno_es_502(cliente: FlaskClient, redis_falso: RedisFalso) -> None:
    _precargar_respuesta(redis_falso, "c-502", codigo="INTERNO", error="excepción no controlada")
    cuerpo = _operacion("c-502", "E-ASN-01", "s1", "asesor", "consultar_poliza")
    respuesta = cliente.post("/v1/operaciones", json=cuerpo)

    assert respuesta.status_code == 502
    assert respuesta.get_json()["type"].endswith("/upstream")


def test_experimento_otp_devuelve_el_codigo_pendiente(cliente: FlaskClient) -> None:
    retenida = _operacion("c-exp", "E-ASN-01", "s1", "supervisor", "aprobar_poliza")
    cliente.post("/v1/operaciones", json=retenida)

    respuesta = cliente.get("/v1/experimento/otp/s1")

    assert respuesta.status_code == 200
    datos = respuesta.get_json()
    assert datos["session_id"] == "s1"
    assert len(datos["codigo"]) == 6
    assert datos["operacion"] == "aprobar_poliza"
    assert datos["creado_en"]


def test_experimento_otp_sin_pendiente_es_404(cliente: FlaskClient) -> None:
    respuesta = cliente.get("/v1/experimento/otp/sin-sesion")
    assert respuesta.status_code == 404
    assert respuesta.get_json()["type"].endswith("/sin-otp-pendiente")


def test_experimento_no_existe_sin_modo_experimento(tmp_path: Path) -> None:
    app = crear_app(configuracion(tmp_path, modo_experimento=False), cliente_redis=RedisFalso())  # type: ignore[arg-type]
    with app.test_client() as c:
        respuesta = c.get("/v1/experimento/otp/s1")
    assert respuesta.status_code == 404
