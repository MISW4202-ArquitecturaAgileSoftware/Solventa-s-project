"""El informe de ASR-11 usa el denominador de fallos efectivos."""

from reporte import denominador_deteccion, notas_denominador_parcial


def test_denominador_prefiere_fallos_efectivos() -> None:
    assert denominador_deteccion({"fallos_efectivos": 9, "alcanzaron_votacion": 12}) == 9


def test_denominador_sin_campo_nuevo() -> None:
    assert denominador_deteccion({"alcanzaron_votacion": 100}) == 100


def test_nota_solo_si_el_modo_no_altera_todas() -> None:
    modos = [
        ("premium_offset", {"fallos_efectivos": 100, "alcanzaron_votacion": 100}),
        ("factor_skip", {"fallos_efectivos": 75, "alcanzaron_votacion": 100}),
    ]
    notas = notas_denominador_parcial(modos)
    assert len(notas) == 1
    assert "`factor_skip`" in notas[0]
    assert "75" in notas[0]
    assert "100" in notas[0]
