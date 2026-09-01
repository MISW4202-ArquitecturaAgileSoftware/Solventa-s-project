"""Ventana fija por socio."""

from api_gateway.limitador import Limitador


def test_permite_hasta_el_limite() -> None:
    limitador = Limitador(3)
    assert [limitador.registrar("socio", 0.0).permitido for _ in range(4)] == [
        True,
        True,
        True,
        False,
    ]


def test_la_ventana_siguiente_reinicia_la_cuenta() -> None:
    limitador = Limitador(2)
    limitador.registrar("socio", 0.0)
    limitador.registrar("socio", 0.0)

    assert limitador.registrar("socio", 30.0).permitido is False
    assert limitador.registrar("socio", 60.0).permitido is True


def test_los_socios_se_cuentan_por_separado() -> None:
    limitador = Limitador(1)
    assert limitador.registrar("uno", 0.0).permitido is True
    assert limitador.registrar("dos", 0.0).permitido is True
    assert limitador.registrar("uno", 0.0).permitido is False


def test_reintentar_en_apunta_al_fin_de_la_ventana() -> None:
    limitador = Limitador(1)
    limitador.registrar("socio", 100.0)
    decision = limitador.registrar("socio", 100.0)

    assert decision.reintentar_en == 20  # 160 - 140... fin del minuto en curso


def test_se_podan_los_socios_de_ventanas_pasadas() -> None:
    """Sin poda, el diccionario crecería con cada socio que apareciera una vez."""
    limitador = Limitador(10)
    for i in range(1100):
        limitador.registrar(f"socio-{i}", 0.0)
    limitador.registrar("nuevo", 600.0)

    assert len(limitador._ventanas) < 1100
