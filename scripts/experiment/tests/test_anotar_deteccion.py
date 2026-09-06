"""La tasa de ASR-11 usa fallos efectivos, y un denominador 0 aborta."""

import json
from pathlib import Path

import pytest

from anotar_deteccion import anotar


def _json(tmp_path: Path, **campos: object) -> Path:
    ruta = tmp_path / "B-factor_skip.json"
    base = {
        "etiqueta": "deteccion-factor_skip",
        "alcanzaron_votacion": 12,
        "fallos_efectivos": 9,
    }
    base.update(campos)
    ruta.write_text(json.dumps(base), encoding="utf-8")
    return ruta


def test_tasa_usa_fallos_efectivos(tmp_path: Path) -> None:
    ruta = _json(tmp_path)
    datos = anotar(ruta, "factor_skip", 10, 19)
    assert datos["incidentes_registrados"] == 9
    assert datos["tasa_deteccion"] == 1.0
    assert json.loads(ruta.read_text(encoding="utf-8"))["modo"] == "factor_skip"


def test_denominador_cero_aborta(tmp_path: Path) -> None:
    ruta = _json(tmp_path, fallos_efectivos=0)
    with pytest.raises(SystemExit, match="no produjo ningún fallo efectivo"):
        anotar(ruta, "factor_skip", 0, 0)
