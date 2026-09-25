from auditor.contracts import (
    Accion,
    Actor,
    CuerpoAnomalia,
    Decision,
    ErrorContrato,
    EventoAuditoria,
    Recurso,
    RespuestaAnomalia,
    Rol,
    ahora_utc,
)

CRUDO_EVENTO = {
    "evento_id": "019a",
    "correlation_id": "019b",
    "tipo": "operacion.auditada",
    "version": "1",
    "emitido_en": "2026-09-21T14:02:10.418Z",
    "actor": {"employee_id": "E-ASN-01", "session_id": "019c", "rol": "asesor"},
    "accion": "CONSULTA_POLIZA",
    "recurso": {
        "tipo": "poliza",
        "poliza_id": "POL-SUR-003",
        "region": "sur",
        "cliente_id": "CLI-SUR-003",
    },
    "resultado": "OK",
}


def test_evento_auditoria_ida_y_vuelta() -> None:
    evento = EventoAuditoria.desde_dict(CRUDO_EVENTO)
    assert evento.actor == Actor(employee_id="E-ASN-01", session_id="019c", rol=Rol.ASESOR)
    assert evento.recurso.region == "sur"
    assert evento.a_dict() == CRUDO_EVENTO


def test_evento_auditoria_recurso_sin_region_es_valido() -> None:
    crudo = dict(CRUDO_EVENTO)
    crudo["recurso"] = {
        "tipo": "poliza",
        "poliza_id": "POL-SUR-999",
        "region": None,
        "cliente_id": None,
    }
    crudo["resultado"] = "NO_ENCONTRADA"
    evento = EventoAuditoria.desde_dict(crudo)
    assert evento.recurso.region is None
    assert evento.recurso.cliente_id is None
    assert evento.a_dict()["recurso"]["region"] is None


def test_evento_auditoria_campo_faltante_es_error_contrato() -> None:
    crudo = dict(CRUDO_EVENTO)
    del crudo["evento_id"]
    try:
        EventoAuditoria.desde_dict(crudo)
    except ErrorContrato as err:
        assert err.campo == "evento_id"
    else:
        raise AssertionError("se esperaba ErrorContrato")


def test_cuerpo_anomalia_tiene_el_cuerpo_exacto_de_3_4() -> None:
    cuerpo = CuerpoAnomalia(
        evento_id="019a",
        correlation_id="019b",
        employee_id="E-ASN-01",
        session_id="019c",
        accion=Accion.CONSULTA_POLIZA,
        region_consultada="sur",
    )
    assert cuerpo.a_dict() == {
        "evento_id": "019a",
        "correlation_id": "019b",
        "employee_id": "E-ASN-01",
        "session_id": "019c",
        "accion": "CONSULTA_POLIZA",
        "region_consultada": "sur",
    }


def test_respuesta_anomalia_desde_dict() -> None:
    respuesta = RespuestaAnomalia.desde_dict({"evento_id": "019a", "decision": "ALERTAR"})
    assert respuesta.decision == Decision.ALERTAR


def test_recurso_desde_dict_directo() -> None:
    recurso = Recurso.desde_dict(
        {
            "tipo": "poliza",
            "poliza_id": "POL-NOR-001",
            "region": "norte",
            "cliente_id": "CLI-NOR-001",
        }
    )
    assert recurso.region == "norte"


def test_ahora_utc_es_consciente_de_zona() -> None:
    assert ahora_utc().tzinfo is not None
