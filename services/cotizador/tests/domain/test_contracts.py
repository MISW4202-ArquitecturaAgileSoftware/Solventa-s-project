"""Entrada de solicitudes y serialización de respuestas del Cotizador."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from cotizador.contracts import (
    SobreRespuesta,
    SobreSolicitud,
    SolicitudCotizacion,
)
from cotizador.errors import ErrorValidacion
from cotizador.pricing import calcular

from .conftest import FECHA_CALCULO

EJEMPLO = Path(__file__).resolve().parents[4] / "docs" / "ejemplos" / "solicitud.json"


def _valida() -> dict[str, Any]:
    return {
        "producto": "vida_hipotecario",
        "moneda": "COP",
        "suma_asegurada": "250000000.00",
        "plazo_meses": 240,
        "canal": "banco_aliado",
        "asegurado": {
            "fecha_nacimiento": "1988-04-17",
            "genero": "F",
            "fumador": False,
            "clase_ocupacional": 2,
        },
        "consentimiento_open_finance": True,
    }


def test_el_ejemplo_del_repositorio_es_valido() -> None:
    """docs/ejemplos/solicitud.json alimenta las validaciones de F3 a F6."""
    solicitud = SolicitudCotizacion.desde_dict(json.loads(EJEMPLO.read_text()))

    assert solicitud.suma_asegurada == Decimal("250000000.00")
    assert calcular(solicitud, FECHA_CALCULO).prima_mensual == Decimal("90348.41")


def test_importe_como_numero_json_es_rechazado() -> None:
    """Un float de JSON no representa dinero exactamente y rompería el
    determinismo entre réplicas."""
    dato = _valida() | {"suma_asegurada": 250000000.00}

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
        SolicitudCotizacion.desde_dict(_valida() | parche)
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
    dato = _valida()
    dato["asegurado"] = dato["asegurado"] | parche

    with pytest.raises(ErrorValidacion):
        SolicitudCotizacion.desde_dict(dato)


def test_campo_ausente_se_reporta_por_nombre() -> None:
    dato = _valida()
    del dato["plazo_meses"]

    with pytest.raises(ErrorValidacion) as excinfo:
        SolicitudCotizacion.desde_dict(dato)
    assert excinfo.value.campo == "plazo_meses"


def test_edad_fuera_de_rango_se_rechaza_en_el_calculo() -> None:
    """La edad depende de fecha_calculo, así que no se valida al deserializar."""
    dato = _valida()
    dato["asegurado"] = dato["asegurado"] | {"fecha_nacimiento": "2015-01-01"}
    solicitud = SolicitudCotizacion.desde_dict(dato)

    with pytest.raises(ErrorValidacion):
        calcular(solicitud, FECHA_CALCULO)


def test_deserializa_el_sobre_de_solicitud() -> None:
    sobre = SobreSolicitud.desde_dict(
        {
            "correlation_id": "01a05aa8-24a1-753e-b019-a0810d66a3f6",
            "tipo": "cotizacion.solicitada",
            "version": "1",
            "emitido_en": "2026-08-31T12:00:00Z",
            "fecha_calculo": "2026-08-31",
            "payload": _valida(),
        }
    )

    assert sobre.fecha_calculo == FECHA_CALCULO
    assert sobre.payload.suma_asegurada == Decimal("250000000.00")


def test_serializa_el_sobre_de_respuesta() -> None:
    from cotizador.contracts import EstadoRespuesta

    resultado = calcular(SolicitudCotizacion.desde_dict(_valida()), FECHA_CALCULO)
    sobre = SobreRespuesta(
        correlation_id="01a05aa8-24a1-753e-b019-a0810d66a3f6",
        cotizador_id="B",
        estado=EstadoRespuesta.OK,
        duracion_ms=7,
        resultado=resultado,
    )
    serializado = json.loads(json.dumps(sobre.a_dict()))

    assert serializado["cotizador_id"] == "B"
    assert serializado["resultado"]["prima_mensual"] == "90348.41"


def test_sobre_de_respuesta_con_error_no_lleva_resultado() -> None:
    from cotizador.contracts import EstadoRespuesta

    sobre = SobreRespuesta(
        correlation_id="01a05aa8-24a1-753e-b019-a0810d66a3f6",
        cotizador_id="C",
        estado=EstadoRespuesta.ERROR,
        duracion_ms=3,
        error="fallo inyectado: crash",
    )
    serializado = json.loads(json.dumps(sobre.a_dict()))

    assert serializado["resultado"] is None
    assert serializado["error"] == "fallo inyectado: crash"


def test_serializa_el_resultado_completo() -> None:
    resultado = calcular(SolicitudCotizacion.desde_dict(_valida()), FECHA_CALCULO)
    serializado = json.loads(json.dumps(resultado.a_dict()))

    assert serializado["prima_mensual"] == "90348.41"
    assert serializado["explicacion"]["factores"]["canal"] == "0.95"


def test_campo_ausente_dice_que_es_obligatorio() -> None:
    """Decirle «debe ser una cadena» a quien ni siquiera envió el campo le hace
    buscar un error de tipo donde no lo hay."""
    dato = _valida()
    del dato["moneda"]

    with pytest.raises(ErrorValidacion) as excinfo:
        SolicitudCotizacion.desde_dict(dato)
    assert excinfo.value.campo == "moneda"
    assert "obligatorio" in excinfo.value.detalle


def test_campo_con_tipo_equivocado_dice_el_tipo() -> None:
    with pytest.raises(ErrorValidacion) as excinfo:
        SolicitudCotizacion.desde_dict(_valida() | {"moneda": 123})
    assert "cadena" in excinfo.value.detalle
