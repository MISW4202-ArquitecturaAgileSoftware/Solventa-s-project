import pytest

from gestion_polizas.contracts import (
    AccionAuditoria,
    Actor,
    CodigoRespuesta,
    ErrorValidacionSobre,
    EstadoRespuesta,
    EventoAuditoria,
    RecursoPoliza,
    SobreOperacion,
    SobreRespuesta,
    ahora_utc,
)


def test_sobre_operacion_ida_y_vuelta() -> None:
    dato = {
        "correlation_id": "c1",
        "tipo": "operacion.solicitada",
        "version": "1",
        "emitido_en": "2026-09-21T00:00:00.000Z",
        "actor": {"employee_id": "E-ASN-01", "session_id": "s1", "rol": "asesor"},
        "operacion": "consultar_poliza",
        "parametros": {"poliza_id": "POL-NOR-001"},
    }
    sobre = SobreOperacion.desde_dict(dato)
    assert sobre.correlation_id == "c1"
    assert sobre.actor.employee_id == "E-ASN-01"
    assert sobre.actor.rol == "asesor"
    assert sobre.operacion == "consultar_poliza"
    assert sobre.parametros["poliza_id"] == "POL-NOR-001"


@pytest.mark.parametrize(
    "campo", ["correlation_id", "tipo", "version", "emitido_en", "actor", "operacion", "parametros"]
)
def test_sobre_operacion_campo_faltante(campo: str) -> None:
    dato = {
        "correlation_id": "c1",
        "tipo": "operacion.solicitada",
        "version": "1",
        "emitido_en": "2026-09-21T00:00:00.000Z",
        "actor": {"employee_id": "E-ASN-01", "session_id": "s1", "rol": "asesor"},
        "operacion": "consultar_poliza",
        "parametros": {"poliza_id": "POL-NOR-001"},
    }
    del dato[campo]
    with pytest.raises(ErrorValidacionSobre):
        SobreOperacion.desde_dict(dato)


def test_actor_campo_faltante() -> None:
    with pytest.raises(ErrorValidacionSobre):
        SobreOperacion.desde_dict(
            {
                "correlation_id": "c1",
                "tipo": "t",
                "version": "1",
                "emitido_en": "x",
                "actor": {"employee_id": "E-ASN-01"},
                "operacion": "consultar_poliza",
                "parametros": {"poliza_id": "POL-NOR-001"},
            }
        )


def test_sobre_respuesta_a_dict_exitosa() -> None:
    respuesta = SobreRespuesta(
        correlation_id="c1",
        estado=EstadoRespuesta.OK,
        codigo=CodigoRespuesta.OK,
        duracion_ms=4,
        resultado={"poliza_id": "POL-NOR-001"},
    )
    cuerpo = respuesta.a_dict()
    assert cuerpo == {
        "correlation_id": "c1",
        "tipo": "operacion.resuelta",
        "servicio": "gestion-polizas",
        "estado": "OK",
        "codigo": "OK",
        "duracion_ms": 4,
        "resultado": {"poliza_id": "POL-NOR-001"},
        "error": None,
    }


def test_sobre_respuesta_a_dict_error() -> None:
    respuesta = SobreRespuesta(
        correlation_id="c1",
        estado=EstadoRespuesta.ERROR,
        codigo=CodigoRespuesta.NO_ENCONTRADA,
        duracion_ms=2,
        error="póliza no encontrada",
    )
    cuerpo = respuesta.a_dict()
    assert cuerpo["estado"] == "ERROR"
    assert cuerpo["codigo"] == "NO_ENCONTRADA"
    assert cuerpo["resultado"] is None
    assert cuerpo["error"] == "póliza no encontrada"


def test_evento_auditoria_sin_datos_sensibles() -> None:
    evento = EventoAuditoria(
        evento_id="e1",
        correlation_id="c1",
        emitido_en=ahora_utc(),
        actor=Actor(employee_id="E-ASN-01", session_id="s1", rol="asesor"),
        accion=AccionAuditoria.CONSULTA_POLIZA,
        recurso=RecursoPoliza(poliza_id="POL-SUR-003", region="sur", cliente_id="CLI-SUR-003"),
        resultado="OK",
    )
    cuerpo = evento.a_dict()
    assert cuerpo["accion"] == "CONSULTA_POLIZA"
    assert cuerpo["recurso"] == {
        "tipo": "poliza",
        "poliza_id": "POL-SUR-003",
        "region": "sur",
        "cliente_id": "CLI-SUR-003",
    }
    assert cuerpo["resultado"] == "OK"
    assert "prima_mensual" not in cuerpo["recurso"]
    assert "suma_asegurada" not in cuerpo["recurso"]
    assert "prima_mensual" not in cuerpo
    assert "suma_asegurada" not in cuerpo


def test_evento_auditoria_poliza_inexistente_region_null() -> None:
    evento = EventoAuditoria(
        evento_id="e2",
        correlation_id="c2",
        emitido_en=ahora_utc(),
        actor=Actor(employee_id="E-ASN-01", session_id="s1", rol="asesor"),
        accion=AccionAuditoria.CONSULTA_POLIZA,
        recurso=RecursoPoliza(poliza_id="POL-NOR-999", region=None, cliente_id=None),
        resultado="NO_ENCONTRADA",
    )
    cuerpo = evento.a_dict()
    assert cuerpo["recurso"]["region"] is None
    assert cuerpo["recurso"]["cliente_id"] is None
    assert cuerpo["resultado"] == "NO_ENCONTRADA"
