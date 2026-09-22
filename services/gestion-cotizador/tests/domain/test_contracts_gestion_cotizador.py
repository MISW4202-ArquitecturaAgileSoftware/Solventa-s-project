"""Entrada de solicitudes y serialización de resultados y sobres."""

import json
from decimal import Decimal
from typing import Any

import pytest
from soporte_gestion_cotizador import FECHA_CALCULO

from gestion_cotizador.contracts import (
    Actor,
    CodigoRespuesta,
    EstadoRespuesta,
    SobreOperacion,
    SobreRespuesta,
    SolicitudCotizacion,
)
from gestion_cotizador.errors import ErrorValidacion


def _asegurado_valido() -> dict[str, Any]:
    return {
        "fecha_nacimiento": "1988-04-17",
        "genero": "F",
        "fumador": False,
        "clase_ocupacional": 2,
    }


def _solicitud_valida() -> dict[str, Any]:
    return {
        "producto": "vida_hipotecario",
        "moneda": "COP",
        "suma_asegurada": "250000000.00",
        "plazo_meses": 240,
        "canal": "banco_aliado",
        "asegurado": _asegurado_valido(),
        "consentimiento_open_finance": True,
    }


def _actor_valido() -> dict[str, Any]:
    return {"employee_id": "E-ASN-01", "session_id": "s1", "rol": "asesor"}


def _sobre_valido() -> dict[str, Any]:
    return {
        "correlation_id": "019a05aa-24a1-753e-b019-a0810d66a3f6",
        "tipo": "operacion.solicitada",
        "version": "1",
        "emitido_en": "2026-08-31T12:00:00Z",
        "actor": _actor_valido(),
        "operacion": "cotizar",
        "parametros": _solicitud_valida(),
        "fecha_calculo": "2026-08-31",
    }


# --- SolicitudCotizacion -----------------------------------------------------


def test_deserializa_solicitud_valida() -> None:
    solicitud = SolicitudCotizacion.desde_dict(_solicitud_valida())

    assert solicitud.suma_asegurada == Decimal("250000000.00")


def test_importe_como_numero_json_es_rechazado() -> None:
    """Un float de JSON no representa dinero exactamente."""
    dato = _solicitud_valida() | {"suma_asegurada": 250000000.00}

    with pytest.raises(ErrorValidacion) as excinfo:
        SolicitudCotizacion.desde_dict(dato)
    assert "cadena decimal" in str(excinfo.value)


@pytest.mark.parametrize(
    ("parche", "campo_esperado"),
    [
        ({"producto": "auto"}, "producto"),
        ({"moneda": "USD"}, "moneda"),
        ({"canal": "telefono"}, "canal"),
        ({"suma_asegurada": "9999999"}, "suma_asegurada"),
        ({"suma_asegurada": "2000000001"}, "suma_asegurada"),
        ({"plazo_meses": 11}, "plazo_meses"),
        ({"plazo_meses": 361}, "plazo_meses"),
        ({"plazo_meses": "240"}, "plazo_meses"),
        ({"consentimiento_open_finance": "si"}, "consentimiento_open_finance"),
    ],
)
def test_campos_fuera_de_contrato(parche: dict[str, Any], campo_esperado: str) -> None:
    with pytest.raises(ErrorValidacion) as excinfo:
        SolicitudCotizacion.desde_dict(_solicitud_valida() | parche)
    assert excinfo.value.campo == campo_esperado


@pytest.mark.parametrize(
    "parche",
    [
        {"clase_ocupacional": 0},
        {"clase_ocupacional": 5},
        {"clase_ocupacional": True},
        {"genero": "otro"},
        {"fecha_nacimiento": "17/04/1988"},
        {"fumador": "no"},
    ],
)
def test_asegurado_fuera_de_contrato(parche: dict[str, Any]) -> None:
    dato = _solicitud_valida()
    dato["asegurado"] = dato["asegurado"] | parche

    with pytest.raises(ErrorValidacion):
        SolicitudCotizacion.desde_dict(dato)


def test_campo_ausente_se_reporta_por_nombre() -> None:
    dato = _solicitud_valida()
    del dato["plazo_meses"]

    with pytest.raises(ErrorValidacion) as excinfo:
        SolicitudCotizacion.desde_dict(dato)
    assert excinfo.value.campo == "plazo_meses"


def test_campo_ausente_dice_que_es_obligatorio() -> None:
    dato = _solicitud_valida()
    del dato["moneda"]

    with pytest.raises(ErrorValidacion) as excinfo:
        SolicitudCotizacion.desde_dict(dato)
    assert excinfo.value.campo == "moneda"
    assert "obligatorio" in excinfo.value.detalle


def test_campo_con_tipo_equivocado_dice_el_tipo() -> None:
    with pytest.raises(ErrorValidacion) as excinfo:
        SolicitudCotizacion.desde_dict(_solicitud_valida() | {"moneda": 123})
    assert "cadena" in excinfo.value.detalle


# --- SobreOperacion (entrada) ------------------------------------------------


def test_deserializa_el_sobre_de_operacion() -> None:
    sobre = SobreOperacion.desde_dict(_sobre_valido())

    assert sobre.correlation_id == "019a05aa-24a1-753e-b019-a0810d66a3f6"
    assert sobre.operacion == "cotizar"
    assert sobre.actor == Actor(employee_id="E-ASN-01", session_id="s1", rol="asesor")
    assert sobre.fecha_calculo() == FECHA_CALCULO
    assert sobre.solicitud_cotizacion().suma_asegurada == Decimal("250000000.00")


def test_sobre_con_operacion_desconocida_no_falla_al_leer_parametros() -> None:
    """Los parámetros de otra operación no tienen por qué ser una cotización;
    leer el sobre no debe intentar interpretarlos como tal."""
    dato = _sobre_valido() | {
        "operacion": "aprobar_poliza",
        "parametros": {"poliza_id": "POL-NOR-001"},
    }
    sobre = SobreOperacion.desde_dict(dato)

    assert sobre.operacion == "aprobar_poliza"


def test_fecha_calculo_ausente_se_rechaza_al_usarla() -> None:
    dato = _sobre_valido()
    del dato["fecha_calculo"]
    sobre = SobreOperacion.desde_dict(dato)

    with pytest.raises(ErrorValidacion) as excinfo:
        sobre.fecha_calculo()
    assert excinfo.value.campo == "fecha_calculo"


def test_fecha_calculo_malformada_se_rechaza_al_usarla() -> None:
    dato = _sobre_valido() | {"fecha_calculo": "31/08/2026"}
    sobre = SobreOperacion.desde_dict(dato)

    with pytest.raises(ErrorValidacion) as excinfo:
        sobre.fecha_calculo()
    assert excinfo.value.campo == "fecha_calculo"


def test_actor_incompleto_se_rechaza() -> None:
    dato = _sobre_valido()
    del dato["actor"]["session_id"]

    with pytest.raises(ErrorValidacion) as excinfo:
        SobreOperacion.desde_dict(dato)
    assert excinfo.value.campo == "session_id"


# --- SobreRespuesta (salida) -------------------------------------------------


def test_serializa_la_respuesta_de_error_sin_resultado() -> None:
    sobre = SobreRespuesta(
        correlation_id="019a05aa-24a1-753e-b019-a0810d66a3f6",
        servicio="gestion-cotizador",
        estado=EstadoRespuesta.ERROR,
        codigo=CodigoRespuesta.VALIDACION,
        duracion_ms=3,
        error="suma_asegurada debe estar entre 10000000 y 2000000000",
    )
    serializado = json.loads(json.dumps(sobre.a_dict()))

    assert serializado["resultado"] is None
    assert serializado["codigo"] == "VALIDACION"
    assert "suma_asegurada" in serializado["error"]
