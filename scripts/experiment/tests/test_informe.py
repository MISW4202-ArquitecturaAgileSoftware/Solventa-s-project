"""El informe de ASR-11 usa el denominador de fallos efectivos."""

import json
from pathlib import Path

import pytest

from reporte import (
    CATALOGO_MODOS,
    VIA,
    denominador_deteccion,
    ficha_modo,
    notas_denominador_parcial,
)


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


def test_catalogo_cubre_todos_los_modos() -> None:
    assert set(CATALOGO_MODOS) == set(VIA)
    crash = ficha_modo("crash")
    assert crash["via"] == "réplica no responde"
    assert "XACK" in crash["inyecta"] or "respuesta" in crash["inyecta"]


def test_informe_usa_tasa_deteccion_de_locust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import reporte

    monkeypatch.setattr(reporte, "RESULTADOS", tmp_path)
    monkeypatch.setattr(reporte, "SALIDA", tmp_path / "out.md")
    (tmp_path / "B-crash.json").write_text(
        json.dumps(
            {
                "fallos_efectivos": 100,
                "alcanzaron_votacion": 100,
                "incidentes_registrados": 100,
                "tasa_deteccion": 1.0,
                "por_http": {"200": 100},
            }
        ),
        encoding="utf-8",
    )
    assert reporte.main() == 0
    texto = (tmp_path / "out.md").read_text(encoding="utf-8")
    assert "| `crash` | réplica no responde | 100 | 100 | 100.00 % |" in texto
    assert "correlation_id" not in texto
    assert "**CUMPLE**" in texto
    assert "**NO CUMPLE**" not in texto
