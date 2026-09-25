from pathlib import Path

from autenticacion import seed
from autenticacion.contracts import Rol
from autenticacion.repositorio import Repositorio


def test_semilla_coincide_con_el_plan() -> None:
    ids = [eid for eid, _, _ in seed.EMPLEADOS]
    assert len(ids) == 13
    assert ids[:10] == [f"E-ASN-{n:02d}" for n in range(1, 11)]
    assert ids[10:12] == ["E-ASM-01", "E-ASM-02"]
    assert ids[12] == "E-SUP-01"
    roles = {eid: rol for eid, _, rol in seed.EMPLEADOS}
    assert roles["E-SUP-01"] is Rol.SUPERVISOR
    assert all(roles[eid] is Rol.ASESOR for eid in ids[:12])
    usuarios = {usuario for _, usuario, _ in seed.EMPLEADOS}
    assert "asesor.norte.01" in usuarios and "supervisor.01" in usuarios


def test_semilla_es_idempotente(tmp_path: Path) -> None:
    repositorio = Repositorio(tmp_path / "a.db")
    repositorio.inicializar()
    assert seed.sembrar(repositorio) == 13
    assert seed.sembrar(repositorio) == 0
    assert repositorio.contar_empleados() == 13
