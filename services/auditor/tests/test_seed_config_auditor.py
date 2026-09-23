from pathlib import Path

import pytest

from auditor import seed
from auditor.config import desde_entorno
from auditor.contracts import ahora_utc
from auditor.repositorio import Repositorio

#: Columna "Historial (Auditor)" de §2.2, transcrita a mano.
PLAN_22 = {
    **{f"E-ASN-{n:02d}": ["norte"] for n in range(1, 11)},
    "E-ASM-01": ["norte"],
    "E-ASM-02": ["norte"],
    "E-SUP-01": ["centro", "norte", "sur"],
}


def test_historial_coincide_con_el_plan(tmp_path: Path) -> None:
    repositorio = Repositorio(tmp_path / "a.db")
    repositorio.inicializar()

    assert seed.sembrar(repositorio) == 15
    for employee_id, regiones in PLAN_22.items():
        habitos = repositorio.habitos(employee_id)
        assert [h.region for h in habitos] == regiones
        assert all(h.conteo == 0 for h in habitos)
    assert {eid for eid, _ in seed.HISTORIAL} == set(PLAN_22)


def test_semilla_es_idempotente(tmp_path: Path) -> None:
    repositorio = Repositorio(tmp_path / "a.db")
    repositorio.inicializar()
    seed.sembrar(repositorio)

    assert seed.sembrar(repositorio) == 0
    assert repositorio.contar() == 15


def test_incorporar_es_idempotente(tmp_path: Path) -> None:
    repositorio = Repositorio(tmp_path / "a.db")
    repositorio.inicializar()
    repositorio.incorporar("E-ASM-01", "centro", ahora_utc())
    repositorio.incorporar("E-ASM-01", "centro", ahora_utc())

    assert [(h.region, h.conteo) for h in repositorio.habitos("E-ASM-01")] == [("centro", 2)]


# --- Configuración ------------------------------------------------------------


@pytest.fixture
def entorno_minimo(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for nombre in (
        "STREAM_AUDITORIA",
        "GRUPO",
        "CONSUMIDOR",
        "PERIODO_AUDITORIA_S",
        "TAMANO_LOTE",
        "TIMEOUT_HTTP_MS",
        "RUTA_DB",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(nombre, raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("URL_VALIDACION", "http://validacion:8000")
    return monkeypatch


def test_valores_por_defecto(entorno_minimo: pytest.MonkeyPatch) -> None:
    config = desde_entorno()
    assert config.stream_auditoria == "auditoria"
    assert config.grupo == "auditor"
    # Fijo, no el hostname: los pendientes sobreviven a recrear el contenedor.
    assert config.consumidor == "auditor-1"
    assert config.periodo_s == 5.0
    assert config.tamano_lote == 100
    assert config.ruta_db == Path("/data/auditor.db")


def test_periodo_admite_fracciones(entorno_minimo: pytest.MonkeyPatch) -> None:
    entorno_minimo.setenv("PERIODO_AUDITORIA_S", "2.5")
    assert desde_entorno().periodo_s == 2.5


@pytest.mark.parametrize(("nombre", "valor"), [("PERIODO_AUDITORIA_S", "0"), ("TAMANO_LOTE", "0")])
def test_valores_no_positivos_se_rechazan(
    entorno_minimo: pytest.MonkeyPatch, nombre: str, valor: str
) -> None:
    entorno_minimo.setenv(nombre, valor)
    with pytest.raises(RuntimeError, match=nombre):
        desde_entorno()


@pytest.mark.parametrize("falta", ["REDIS_URL", "URL_VALIDACION"])
def test_variables_obligatorias(entorno_minimo: pytest.MonkeyPatch, falta: str) -> None:
    entorno_minimo.delenv(falta)
    with pytest.raises(RuntimeError, match=falta):
        desde_entorno()
