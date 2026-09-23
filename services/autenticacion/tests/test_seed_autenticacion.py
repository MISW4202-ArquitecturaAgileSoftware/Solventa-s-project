from pathlib import Path

from autenticacion import claves, seed
from autenticacion.contracts import Rol
from autenticacion.repositorio import Repositorio

#: La tabla de §2.2, transcrita a mano: si la semilla y el plan divergen, falla.
PLAN_22 = [
    *[(f"E-ASN-{n:02d}", f"asesor.norte.{n:02d}", Rol.ASESOR) for n in range(1, 11)],
    ("E-ASM-01", "asesor.mixto.01", Rol.ASESOR),
    ("E-ASM-02", "asesor.mixto.02", Rol.ASESOR),
    ("E-SUP-01", "supervisor.01", Rol.SUPERVISOR),
]


def test_empleados_coinciden_con_el_plan() -> None:
    assert list(seed.EMPLEADOS) == PLAN_22
    assert seed.PASSWORD == "solventa"


def test_semilla_es_idempotente(tmp_path: Path) -> None:
    repositorio = Repositorio(tmp_path / "a.db")
    repositorio.inicializar()

    assert seed.sembrar(repositorio) == 13
    assert repositorio.contar_empleados() == 13
    assert seed.sembrar(repositorio) == 0
    assert repositorio.contar_empleados() == 13


def test_contrasenas_con_hash_y_sal_propia(base_sembrada: Path) -> None:
    repositorio = Repositorio(base_sembrada / "autenticacion.db")
    hashes = []
    for employee_id, usuario, rol in PLAN_22:
        empleado = repositorio.empleado(employee_id)
        assert empleado is not None
        assert empleado.usuario == usuario
        assert empleado.rol is rol
        assert empleado.bloqueado_en is None
        assert "solventa" not in empleado.hash_password
        assert empleado.hash_password.startswith("scrypt$")
        assert claves.verificar("solventa", empleado.hash_password)
        hashes.append(empleado.hash_password)
    # Misma contraseña, sales distintas ⇒ hashes distintos.
    assert len(set(hashes)) == 13
