"""Persistencia y consulta del fichero JSONL."""

from pathlib import Path
from typing import Any

from gestion_errores.repositorio import RepositorioIncidentes


def test_metricas_sobre_fichero_vacio(tmp_path: Path) -> None:
    repositorio = RepositorioIncidentes(tmp_path / "i.jsonl")
    metricas = repositorio.metricas()

    assert metricas.total == 0
    assert metricas.por_tipo == {}


def test_el_repositorio_crea_el_directorio(tmp_path: Path) -> None:
    ruta = tmp_path / "sub" / "dir" / "i.jsonl"
    RepositorioIncidentes(ruta)
    assert ruta.exists()


def test_todos_respeta_el_limite(tmp_path: Path) -> None:
    repositorio = RepositorioIncidentes(tmp_path / "i.jsonl")
    for i in range(10):
        repositorio.anexar({"correlation_id": str(i)})

    ultimos: list[Any] = repositorio.todos(limite=3)
    assert [incidente["correlation_id"] for incidente in ultimos] == ["7", "8", "9"]
