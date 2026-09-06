"""El generador de solicitudes es determinista y recorre el tarifario."""

from datetime import date

from locust_carga.solicitudes import CLASES, solicitud_de

HOY = date(2026, 8, 31)


def test_solicitud_de_es_estable() -> None:
    esperada = {
        "request_id": "experiment-00000000",
        "producto": "vida_hipotecario",
        "moneda": "COP",
        "suma_asegurada": "80000000.00",
        "plazo_meses": 60,
        "canal": "banco_aliado",
        "asegurado": {
            "fecha_nacimiento": "2004-01-01",
            "genero": "F",
            "fumador": True,
            "clase_ocupacional": 1,
        },
        "consentimiento_open_finance": True,
    }
    assert solicitud_de(0, HOY) == esperada
    assert solicitud_de(0, HOY) == solicitud_de(0, HOY)


def test_solicitud_de_recorre_las_cuatro_clases() -> None:
    clases = {solicitud_de(i, HOY)["asegurado"]["clase_ocupacional"] for i in range(len(CLASES))}
    assert clases == set(CLASES)
