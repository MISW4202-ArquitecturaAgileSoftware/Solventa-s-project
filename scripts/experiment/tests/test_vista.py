import json
from pathlib import Path
from typing import Any

import estado
import reporte
import vista


def _corrida(periodo: int, repeticion: int) -> dict[str, Any]:
    sufijo = f"p{periodo}r{repeticion}"
    usuario = f"asesor.norte.04-{sufijo}"
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
                "estado_aprobacion_2": 401,
                "tipo_error_aprobacion_2": "sesion-revocada",
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
                "estado_consulta_1": 200,
                "estado_consulta_2": 401,
                "tipo_error_consulta_2": "sesion-revocada",
            },
            "legitimo_inusual_asr31": {
                "employee_id": "E-ASM-01",
                "poliza_id": "POL-CEN-001",
                "session_id": f"inusual31-{sufijo}",
                "estado_consulta_1": 200,
                "estado_consulta_2": 200,
            },
        },
        "locust_filas": [
            {"usuario": usuario, "t": 0.0, "estado": 200, "tipo": None},
            {"usuario": usuario, "t": 0.12, "estado": 200, "tipo": None},
            {"usuario": usuario, "t": 0.5, "estado": 401, "tipo": "sesion-revocada"},
        ],
        "alertas": [
            {
                "session_id": f"atacante23-{sufijo}",
                "employee_id": "E-ASN-01",
                "motivo": "OTP_FALLIDO",
                "revocada_en": "2026-09-21T00:00:01Z",
            },
            {
                "session_id": f"atacante31-{sufijo}",
                "employee_id": "E-ASN-03",
                "motivo": "ALCANCE_NO_AUTORIZADO",
                "revocada_en": "2026-09-21T00:00:01Z",
            },
            {
                "session_id": f"inusual31-{sufijo}",
                "employee_id": "E-ASM-01",
                "motivo": "CONSULTA_INUSUAL",
                "revocada_en": None,
            },
        ],
        "alertas_duplicadas_en_logs": 4,
        "estados_polizas": {"POL-NOR-001": "PENDIENTE", "POL-NOR-002": "APROBADA"},
    }


def _publicar(raiz: Path, corrida_dir: Path, cuerpo: dict[str, Any]) -> None:
    (raiz / "actual.json").write_text(
        json.dumps({"directorio": str(corrida_dir.resolve())}), encoding="utf-8"
    )
    (corrida_dir / "estado.json").write_text(json.dumps(cuerpo), encoding="utf-8")


def test_sin_puntero_esta_esperando(tmp_path: Path) -> None:
    assert vista.construir_vista(tmp_path)["fase"] == "esperando"


def test_rechaza_un_puntero_fuera_de_resultados(tmp_path: Path) -> None:
    (tmp_path / "actual.json").write_text(json.dumps({"directorio": "/etc"}), encoding="utf-8")
    assert vista.construir_vista(tmp_path)["fase"] == "esperando"


def test_criterios_coinciden_con_el_informe_y_la_rafaga_ignora_la_linea_a_medias(
    tmp_path: Path,
) -> None:
    corrida_dir = tmp_path / "20260924T000000Z"
    corrida_dir.mkdir()
    corrida = _corrida(2, 1)
    (corrida_dir / "p2-r1.json").write_text(json.dumps(corrida), encoding="utf-8")
    (corrida_dir / "meta.json").write_text(
        json.dumps({"fecha": "2026-09-24T00:00:00Z", "periodos": [2], "repeticiones": 1}),
        encoding="utf-8",
    )
    (corrida_dir / "p2-r1-locust.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"usuario": "asesor.norte.05", "t": 0.0, "estado": 200, "tipo": None}),
                json.dumps(
                    {
                        "usuario": "asesor.norte.05",
                        "t": 0.4,
                        "estado": 401,
                        "tipo": "sesion-revocada",
                    }
                ),
                '{"usuario": "asesor.norte.06", "t":',
            ]
        ),
        encoding="utf-8",
    )
    _publicar(
        tmp_path,
        corrida_dir,
        {
            "fase": "en_curso",
            "fecha_inicio": "2026-09-24T00:00:00Z",
            "periodos": [2, 5],
            "repeticiones": 3,
            "periodo_actual": 2,
            "repeticion_actual": 2,
            "paso_actual": "locust",
            "jsonl": "p2-r1-locust.jsonl",
            "informe": None,
            "pasos": [
                {
                    "id": "locust",
                    "titulo": "Ráfaga Locust",
                    "estado": "en_curso",
                    "detalle": "",
                }
            ],
        },
    )

    pagina = vista.construir_vista(tmp_path)
    informe = reporte.generar_informe(corrida_dir)

    assert pagina["corridas_cerradas"] == 1
    assert pagina["corridas_totales"] == 6
    assert pagina["criterios_definitivos"] is False
    assert pagina["criterios"]
    for criterio in pagina["criterios"]:
        assert criterio["valor_observado"] in informe
        assert criterio["descripcion"]
        assert criterio["descripcion"] in informe
    assert pagina["ventana"][0]["periodo_auditoria_s"] == 2
    assert pagina["rafaga"] == [
        {
            "usuario": "asesor.norte.05",
            "consultas_200": 1,
            "respuestas_401": 1,
            "ventana_ms": 400.0,
            "revocado": True,
        }
    ]


def test_la_corrida_publica_cada_paso(tmp_path: Path) -> None:
    corrida = estado.CorridaEnCurso(tmp_path / "corrida", [2], 1, tmp_path / "actual.json")
    corrida.empezar_repeticion(2, 1)
    corrida.comenzar("reinicio")
    corrida.cerrar("reinicio", "ok", "stack listo")

    guardado = json.loads((tmp_path / "corrida" / "estado.json").read_text(encoding="utf-8"))
    assert guardado["paso_actual"] is None
    assert guardado["pasos"][0] == {
        "id": "reinicio",
        "titulo": "Reinicio del stack",
        "estado": "ok",
        "detalle": "stack listo",
    }
    assert not (tmp_path / "corrida" / "estado.json.tmp").exists()


def test_juicios_de_paso() -> None:
    assert estado.exito_atacante_asr23(_corrida(2, 1)["escenarios"]["atacante_asr23"])
    assert not estado.exito_atacante_asr31(
        {"estado_consulta_1": 200, "estado_consulta_2": 200, "tipo_error_consulta_2": None}
    )
    assert estado.exito_rafaga(
        [
            {"usuario": "asesor.norte.04", "t": 0.0, "estado": 200, "tipo": None},
            {"usuario": "asesor.norte.04", "t": 0.2, "estado": 401, "tipo": "sesion-revocada"},
        ]
    )
    assert not estado.exito_rafaga([])
    assert estado.exito_cierre({"POL-NOR-001": "PENDIENTE"}, {"POL-NOR-001": "PENDIENTE"})
    assert not estado.exito_cierre({"POL-NOR-001": "APROBADA"}, {"POL-NOR-001": "PENDIENTE"})
