"""El tablero acumula A/B/C sin esperar al informe final."""

from pathlib import Path

from tablero import Tablero


def test_empieza_con_todos_pendientes(tmp_path: Path) -> None:
    panel = Tablero(tmp_path / "estado.json", ("premium_offset", "crash"))
    datos = panel.a_dict()
    assert datos["A"]["estado"] == "pendiente"
    assert datos["B"]["crash"]["estado"] == "pendiente"
    assert datos["asr11"]["estado"] == "pendiente"
    assert datos["asr12"]["estado"] == "pendiente"


def test_asr11_parcial_luego_cumple(tmp_path: Path) -> None:
    panel = Tablero(tmp_path / "estado.json", ("premium_offset", "crash"))
    panel.b_en_curso("premium_offset")
    assert panel.a_dict()["B"]["premium_offset"]["estado"] == "en_curso"
    panel.registrar_b(
        "premium_offset",
        {
            "tasa_deteccion": 1.0,
            "fallos_efectivos": 100,
            "alcanzaron_votacion": 100,
            "incidentes_registrados": 100,
            "primas_erroneas": 0,
        },
    )
    parcial = panel.a_dict()["asr11"]
    assert parcial["estado"] == "parcial"
    assert parcial["modos_hechos"] == 1
    panel.registrar_b(
        "crash",
        {
            "tasa_deteccion": 1.0,
            "fallos_efectivos": 100,
            "alcanzaron_votacion": 100,
            "incidentes_registrados": 100,
            "primas_erroneas": 0,
        },
    )
    final = panel.a_dict()["asr11"]
    assert final["estado"] == "hecho"
    assert final["cumple"] is True


def test_asr12_cuando_existen_a_y_c(tmp_path: Path) -> None:
    panel = Tablero(tmp_path / "estado.json", ("premium_offset",))
    panel.registrar_a(
        {
            "enviadas": 200,
            "tasa_real_por_minuto": 500,
            "latencia_ms": {"p50": 10, "p95": 20, "p99": 30},
            "primas_erroneas": 0,
        }
    )
    assert panel.a_dict()["asr12"]["estado"] == "pendiente"
    panel.registrar_c(
        {
            "enviadas": 200,
            "tasa_real_por_minuto": 500,
            "latencia_ms": {"p50": 11, "p95": 22, "p99": 33},
            "primas_erroneas": 0,
            "por_estado_cotizacion": {"COTIZADO": 200},
        }
    )
    asr12 = panel.a_dict()["asr12"]
    assert asr12["retardo_ms"] == 2.0
    assert asr12["cumple"] is True
