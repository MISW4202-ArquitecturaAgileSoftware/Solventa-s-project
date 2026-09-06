"""El orquestador fija tamaños, el comando de Locust y el orden de la corrida B."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from correr import (
    _esperar_salida,
    comando_locust,
    corrida_deteccion,
    segundos_tope,
    tamanos,
)


def test_tamanos_oficiales() -> None:
    assert tamanos(rapido=False) == (5000, 1000, 5000)


def test_tamanos_rapido() -> None:
    assert tamanos(rapido=True) == (200, 100, 200)


def test_comando_locust_abre_ui() -> None:
    comando = comando_locust(
        host="http://localhost:8000",
        segundos=150,
        sin_ui=False,
        puerto=8089,
        mantener_ui=True,
    )
    assert "--autostart" in comando
    assert "--headless" not in comando
    assert "--autoquit" not in comando
    assert "--run-time" not in comando
    assert "8089" in comando


def test_comando_locust_sin_ui() -> None:
    comando = comando_locust(
        host="http://localhost:8000",
        segundos=150,
        sin_ui=True,
        puerto=8089,
    )
    assert "--headless" in comando
    assert "--autostart" not in comando


def test_segundos_tope_incluye_margen() -> None:
    # Ritmo efectivo 80 % de 500/min = 400/min → 150 s, más 90 s de margen.
    assert segundos_tope(1000, 500) == 240


def test_esperar_salida_acepta_el_json_escrito_al_terminar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    salida = tmp_path / "A-baseline.json"

    def terminar(_proceso: object) -> None:
        salida.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("correr._terminar", terminar)
    monkeypatch.setattr("correr.time.sleep", lambda _s: None)
    proceso = SimpleNamespace(poll=lambda: None)
    _esperar_salida(salida, proceso, 0.0)  # type: ignore[arg-type]


def test_corrida_b_inyecta_un_modo_por_vez(tmp_path: Path) -> None:
    pasos: list[tuple[object, ...]] = []

    def inyectar(replica: str, modo: str) -> None:
        pasos.append(("inyectar", replica, modo))

    def carga(etiqueta: str, n: int, salida: Path, modo: str) -> None:
        pasos.append(("carga", etiqueta, n, modo))
        salida.write_text("{}", encoding="utf-8")

    def leer() -> int:
        return 10

    def esperar() -> int:
        pasos.append(("esperar",))
        return 20

    def anotar(ruta: Path, modo: str, antes: int, despues: int) -> dict[str, object]:
        pasos.append(("anotar", modo, antes, despues, ruta.name))
        return {"incidentes_registrados": 10, "fallos_efectivos": 10, "tasa_deteccion": 1.0}

    corrida_deteccion(
        ["premium_offset", "crash"],
        100,
        tmp_path,
        inyectar_fn=inyectar,
        carga_fn=carga,
        leer_total=leer,
        esperar=esperar,
        anotar=anotar,
    )

    assert pasos[0] == ("inyectar", "b", "premium_offset")
    assert pasos[1] == ("carga", "deteccion-premium_offset", 100, "premium_offset")
    assert pasos[2] == ("esperar",)
    assert pasos[3][:4] == ("anotar", "premium_offset", 10, 20)
    assert pasos[4] == ("inyectar", "b", "crash")
    assert pasos[5] == ("carga", "deteccion-crash", 100, "crash")
