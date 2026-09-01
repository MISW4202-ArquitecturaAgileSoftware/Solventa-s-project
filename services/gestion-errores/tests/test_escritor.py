"""El escritor en segundo plano y su cola acotada."""

from pathlib import Path
from typing import Any

import pytest

from gestion_errores.escritor import ColaLlenaError, EscritorIncidentes
from gestion_errores.repositorio import RepositorioIncidentes


def test_la_cola_llena_falla_en_vez_de_bloquear(tmp_path: Path) -> None:
    """Hacer esperar a quien reporta consumiría el presupuesto de ASR-12.
    Perder evidencia es malo; frenar el journey del cliente es peor."""
    repositorio = RepositorioIncidentes(tmp_path / "i.jsonl")
    # Capacidad 1 y sin arrancar el hilo: nada vacía la cola.
    escritor = EscritorIncidentes(repositorio, capacidad=1)

    escritor.encolar({"correlation_id": "1"})
    with pytest.raises(ColaLlenaError):
        escritor.encolar({"correlation_id": "2"})

    assert escritor.perdidos == 1


def test_detener_vacia_lo_pendiente(tmp_path: Path) -> None:
    """Sin esto, cada despliegue perdería los incidentes ya aceptados."""
    ruta = tmp_path / "i.jsonl"
    repositorio = RepositorioIncidentes(ruta)
    escritor = EscritorIncidentes(repositorio, capacidad=100)
    escritor.iniciar()

    for i in range(50):
        escritor.encolar({"correlation_id": str(i), "tipo": "sin_quorum"})
    escritor.detener()

    assert len(ruta.read_text(encoding="utf-8").strip().splitlines()) == 50


def test_un_fallo_de_escritura_no_mata_el_hilo(tmp_path: Path) -> None:
    """Si el hilo muriera, el servicio seguiría devolviendo 202 y perdiéndolo
    todo en silencio."""
    repositorio = RepositorioIncidentes(tmp_path / "i.jsonl")
    escritor = EscritorIncidentes(repositorio, capacidad=100)
    escritor.iniciar()

    # Un objeto no serializable revienta json.dumps dentro del hilo.
    escritor.encolar({"correlation_id": "malo", "raro": object()})
    escritor.encolar({"correlation_id": "bueno", "tipo": "sin_quorum"})
    escritor.detener()

    assert escritor.esta_vivo() is False  # terminó por el centinela, no por el error
    contenido = repositorio.ruta.read_text(encoding="utf-8")
    assert "bueno" in contenido
    assert "malo" not in contenido


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
    assert [i["correlation_id"] for i in ultimos] == ["7", "8", "9"]
