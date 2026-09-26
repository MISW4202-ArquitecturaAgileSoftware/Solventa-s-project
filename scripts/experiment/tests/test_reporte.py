import json
from pathlib import Path
from typing import Any

import reporte


def _corrida(
    periodo: int, repeticion: int, *, bloqueada: bool = True, fuga: bool = True
) -> dict[str, Any]:
    sufijo = f"p{periodo}r{repeticion}"
    return {
        "periodo_auditoria_s": periodo,
        "repeticion": repeticion,
        "escenarios": {
            "atacante_asr23": {
                "employee_id": "E-ASN-01",
                "poliza_id": "POL-NOR-001",
                "session_id": f"atacante23-{sufijo}",
                "estado_aprobacion_1": 202,
                "estado_otp": 403,
                "tipo_error_otp": "otp-fallido",
                "estado_aprobacion_2": 401 if bloqueada else 200,
                "tipo_error_aprobacion_2": "sesion-revocada" if bloqueada else None,
                "latencia_revocacion_ms": 120.0,
            },
            "legitimo_asr23": {
                "employee_id": "E-ASN-02",
                "poliza_id": "POL-NOR-002",
                "session_id": f"legitimo23-{sufijo}",
                "estado_aprobacion_1": 202,
                "estado_otp": 200,
                "estado_operacion_resultado": "APROBADA",
                "estado_consulta_2": 200,
            },
            "atacante_asr31_secuencial": {
                "employee_id": "E-ASN-03",
                "poliza_id": "POL-SUR-001",
                "session_id": f"atacante31-{sufijo}",
                "estado_consulta_1": 200 if fuga else 401,
                "estado_consulta_2": 401 if bloqueada else 200,
                "tipo_error_consulta_2": "sesion-revocada" if bloqueada else None,
            },
            "legitimo_inusual_asr31": {
                "employee_id": "E-ASM-01",
                "poliza_id": "POL-CEN-001",
                "session_id": f"inusual31-{sufijo}",
                "estado_consulta_1": 200,
                "estado_consulta_2": 200,
            },
        },
        "locust_filas": (
            [
                {"usuario": f"asesor.norte.04-{sufijo}", "t": 0.0, "estado": 200, "tipo": None},
                {"usuario": f"asesor.norte.04-{sufijo}", "t": 0.2, "estado": 200, "tipo": None},
                {
                    "usuario": f"asesor.norte.04-{sufijo}",
                    "t": 0.2 + periodo,
                    "estado": 401,
                    "tipo": "sesion-revocada",
                },
            ]
            if fuga
            else [
                {
                    "usuario": f"asesor.norte.04-{sufijo}",
                    "t": 0.0,
                    "estado": 401,
                    "tipo": "sesion-revocada",
                }
            ]
        ),
        "alertas": [
            {
                "session_id": f"atacante23-{sufijo}",
                "employee_id": "E-ASN-01",
                "motivo": "OTP_FALLIDO",
                "revocada_en": "2026-09-21T00:00:01Z" if bloqueada else None,
            },
            {
                "session_id": f"atacante31-{sufijo}",
                "employee_id": "E-ASN-03",
                "motivo": "ALCANCE_NO_AUTORIZADO",
                "revocada_en": "2026-09-21T00:00:01Z" if bloqueada else None,
            },
            {
                "session_id": f"inusual31-{sufijo}",
                "employee_id": "E-ASM-01",
                "motivo": "CONSULTA_INUSUAL",
                "revocada_en": None,
            },
        ],
        "alertas_duplicadas_en_logs": 0,
        "estados_polizas": {"POL-NOR-001": "PENDIENTE", "POL-NOR-002": "APROBADA"},
    }


def _escribir_corridas(directorio: Path, corridas: list[dict[str, Any]]) -> None:
    for corrida in corridas:
        nombre = f"p{corrida['periodo_auditoria_s']}-r{corrida['repeticion']}.json"
        (directorio / nombre).write_text(json.dumps(corrida), encoding="utf-8")
    meta = {"fecha": "2026-09-21T00:00:00Z", "periodos": [2, 5], "repeticiones": 1, "imagenes": {}}
    (directorio / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_generar_informe_todo_cumple(tmp_path: Path) -> None:
    _escribir_corridas(tmp_path, [_corrida(2, 1, fuga=False), _corrida(5, 1, fuga=False)])

    informe = reporte.generar_informe(tmp_path)

    assert "# Resultados del experimento" in informe
    assert "## Criterios de aceptación" in informe
    assert "## Ventana de exposición por `PERIODO_AUDITORIA_S`" in informe
    assert "| 2 |" in informe
    assert "| 5 |" in informe
    criterios = informe.split("## Criterios de aceptación")[1].split("## Ventana")[0]
    assert "| NO |" not in criterios


def test_generar_informe_marca_incumplimiento(tmp_path: Path) -> None:
    _escribir_corridas(tmp_path, [_corrida(2, 1, bloqueada=False)])

    informe = reporte.generar_informe(tmp_path)
    tabla_criterios = informe.split("## Criterios de aceptación")[1].split("## Ventana")[0]

    assert "segunda operación bloqueada" in tabla_criterios
    assert "| 0% | NO |" in tabla_criterios


def test_un_200_antes_del_401_incumple_el_cierre_de_asr31(tmp_path: Path) -> None:
    _escribir_corridas(tmp_path, [_corrida(2, 1)])

    informe = reporte.generar_informe(tmp_path)
    tabla = informe.split("## Criterios de aceptación")[1].split("## Ventana")[0]

    assert "operaciones del atacante antes de cerrar la sesión" in tabla
    assert "| 3 | NO |" in tabla


def test_generar_informe_falla_sin_corridas(tmp_path: Path) -> None:
    try:
        reporte.generar_informe(tmp_path)
    except RuntimeError:
        pass
    else:
        raise AssertionError("debía fallar sin corridas")
