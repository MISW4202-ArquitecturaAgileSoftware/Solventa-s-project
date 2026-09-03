"""Modelo de vista del reporte: qué, cuándo y cómo de cada incidente."""

from datetime import UTC, datetime
from typing import Any

from gestion_errores.contracts import TipoIncidente
from gestion_errores.reporte import _TIPOS, NO_APLICA, CampoComparado, construir


def _campo(incidente: dict[str, Any], nombre: str) -> CampoComparado:
    [fila] = construir([incidente]).incidentes
    return next(campo for campo in fila.comparacion if campo.nombre == nombre)


def test_todo_tipo_de_incidente_tiene_descripcion() -> None:
    assert set(_TIPOS) == set(TipoIncidente)


def test_el_que_describe_el_tipo_y_las_replicas(incidente: dict[str, Any]) -> None:
    [fila] = construir([incidente]).incidentes

    assert fila.tipo_etiqueta == "Divergencia de resultado"
    assert fila.replicas_divergentes == ("B",)
    assert fila.campos_divergentes == ("prima_mensual",)


def test_el_cuando_se_formatea_en_utc(incidente: dict[str, Any]) -> None:
    [fila] = construir([incidente | {"detectado_en": "2026-08-31T15:41:07.512-05:00"}]).incidentes

    assert fila.detectado_en_iso == "2026-08-31T20:41:07.512Z"
    assert fila.detectado_en_texto == "31/08/2026 20:41:07.512 UTC"


def test_el_como_marca_solo_la_celda_que_difiere(incidente: dict[str, Any]) -> None:
    campo = _campo(incidente, "prima_mensual")

    assert campo.difiere is True
    assert [(celda.cotizador_id, celda.valor, celda.difiere) for celda in campo.celdas] == [
        ("A", "90348.41", False),
        ("B", "103900.67", True),
        ("C", "90348.41", False),
    ]
    assert _campo(incidente, "prima_anual").difiere is False


def test_los_campos_anidados_se_aplanan_con_puntos(incidente: dict[str, Any]) -> None:
    assert _campo(incidente, "explicacion.factores.fumador").celdas[0].valor == "1.00"


def test_una_replica_que_fallo_no_cuenta_como_diferencia(incidente: dict[str, Any]) -> None:
    valores = incidente["valores_recibidos"]
    caida = valores[0] | {"resultado": None, "error": "timeout tras 250 ms"}
    registro = incidente | {
        "tipo": "replica_no_responde",
        "replicas_divergentes": ["A"],
        "valores_recibidos": [caida, valores[2], valores[2] | {"cotizador_id": "B"}],
    }

    [fila] = construir([registro]).incidentes

    assert fila.campos_divergentes == ()
    replica_a = fila.replicas[0]
    assert replica_a.respondio is False
    assert replica_a.error == "timeout tras 250 ms"
    assert replica_a.divergente is True
    assert _campo(registro, "prima_mensual").celdas[0].valor == NO_APLICA


def test_sin_mayoria_se_marcan_todas_las_que_no_coinciden(incidente: dict[str, Any]) -> None:
    valores = incidente["valores_recibidos"]
    registro = incidente | {
        "tipo": "sin_quorum",
        "valores_recibidos": [
            valores[0],
            valores[1],
            valores[2] | {"resultado": valores[2]["resultado"] | {"prima_mensual": "1.00"}},
        ],
    }

    assert [celda.difiere for celda in _campo(registro, "prima_mensual").celdas] == [
        True,
        True,
        True,
    ]


def test_sin_replicas_no_hay_comparacion(incidente: dict[str, Any]) -> None:
    [fila] = construir([incidente | {"valores_recibidos": []}]).incidentes

    assert fila.replicas == ()
    assert fila.comparacion == ()


def test_un_instante_ilegible_se_muestra_crudo(incidente: dict[str, Any]) -> None:
    [fila] = construir([incidente | {"detectado_en": "ayer"}]).incidentes

    assert fila.detectado_en_iso == ""
    assert fila.detectado_en_texto == "ayer"


def test_un_tipo_desconocido_no_impide_el_reporte(incidente: dict[str, Any]) -> None:
    """El fichero puede traer registros de otra versión del contrato."""
    [fila] = construir([incidente | {"tipo": "regla_de_validez"}]).incidentes

    assert fila.tipo_etiqueta == "regla_de_validez"
    assert "no reconoce" in fila.tipo_explicacion


def test_el_mas_reciente_va_primero(incidente: dict[str, Any]) -> None:
    primero = incidente | {"correlation_id": "primero"}
    segundo = incidente | {"correlation_id": "segundo"}

    reporte = construir([primero, segundo])

    assert [fila.correlation_id for fila in reporte.incidentes] == ["segundo", "primero"]


def test_resumen_por_tipo_y_replica(incidente: dict[str, Any]) -> None:
    otro = incidente | {"tipo": "sin_quorum", "replicas_divergentes": ["B", "C"]}

    reporte = construir([incidente, otro], filtro_correlation_id=None)

    assert reporte.total == 2
    assert reporte.por_tipo == (("Divergencia de resultado", 1), ("Sin quórum", 1))
    assert reporte.por_replica == (("B", 2), ("C", 1))


def test_generado_en_es_fijable_para_reportes_reproducibles() -> None:
    reporte = construir([], generado_en=datetime(2026, 9, 2, 20, 0, tzinfo=UTC))

    assert reporte.generado_en_iso == "2026-09-02T20:00:00.000Z"
    assert reporte.generado_en_texto == "02/09/2026 20:00:00.000 UTC"
    assert reporte.incidentes == ()
