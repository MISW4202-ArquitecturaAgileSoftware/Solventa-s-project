"""Validación del payload de entrada (§1.2) e ida y vuelta de la serialización."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from cotizador.common.contracts import (
    ResultadoCotizacion,
    SobreRespuesta,
    SobreSolicitud,
    SolicitudCotizacion,
    ahora_utc,
)
from cotizador.common.errors import ErrorValidacion
from cotizador.common.pricing import calcular

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


def test_ida_y_vuelta_conserva_la_solicitud() -> None:
    original = SolicitudCotizacion.desde_dict(_valida())
    assert SolicitudCotizacion.desde_dict(original.a_dict()) == original


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


def test_ida_y_vuelta_del_sobre_de_solicitud() -> None:
    sobre = SobreSolicitud(
        correlation_id="01a05aa8-24a1-753e-b019-a0810d66a3f6",
        emitido_en=ahora_utc(),
        fecha_calculo=date(2026, 8, 31),
        tarifario_version="2026.02",
        payload=SolicitudCotizacion.desde_dict(_valida()),
    )
    ida = json.loads(json.dumps(sobre.a_dict()))

    assert SobreSolicitud.desde_dict(ida) == sobre


def test_ida_y_vuelta_del_sobre_de_respuesta() -> None:
    from cotizador.common.contracts import EstadoRespuesta
    from cotizador.common.hashing import resultado_hash

    resultado = calcular(SolicitudCotizacion.desde_dict(_valida()), FECHA_CALCULO)
    sobre = SobreRespuesta(
        correlation_id="01a05aa8-24a1-753e-b019-a0810d66a3f6",
        cotizador_id="B",
        estado=EstadoRespuesta.OK,
        duracion_ms=7,
        resultado_hash=resultado_hash(resultado),
        resultado=resultado,
    )
    ida = json.loads(json.dumps(sobre.a_dict()))

    assert SobreRespuesta.desde_dict(ida) == sobre


def test_sobre_de_respuesta_con_error_no_lleva_resultado() -> None:
    from cotizador.common.contracts import EstadoRespuesta

    sobre = SobreRespuesta(
        correlation_id="01a05aa8-24a1-753e-b019-a0810d66a3f6",
        cotizador_id="C",
        estado=EstadoRespuesta.ERROR,
        duracion_ms=3,
        error="fallo inyectado: crash",
    )
    ida = json.loads(json.dumps(sobre.a_dict()))
    reconstruido = SobreRespuesta.desde_dict(ida)

    assert reconstruido.resultado is None
    assert reconstruido.resultado_hash is None
    assert reconstruido == sobre


def test_ida_y_vuelta_del_resultado() -> None:
    resultado = calcular(SolicitudCotizacion.desde_dict(_valida()), FECHA_CALCULO)
    ida = json.loads(json.dumps(resultado.a_dict()))

    assert ResultadoCotizacion.desde_dict(ida) == resultado


@pytest.mark.parametrize("valor", ["ayer", "", "2026-13-45T99:99:99Z", "1788229562"])
def test_instante_malformado_da_error_de_validacion(valor: str) -> None:
    """Sin esto, un instante mal formado subiría como ValueError y el servicio
    respondería 500 en lugar del 422 que exige el contrato."""
    from cotizador.common.contracts import Incidente

    dato = {
        "correlation_id": "01a05aa8-24a1-753e-b019-a0810d66a3f6",
        "tipo": "sin_quorum",
        "detectado_en": valor,
    }
    with pytest.raises(ErrorValidacion) as excinfo:
        Incidente.desde_dict(dato)
    assert excinfo.value.campo == "detectado_en"


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
