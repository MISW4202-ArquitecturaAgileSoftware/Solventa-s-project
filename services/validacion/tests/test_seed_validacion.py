from pathlib import Path

from validacion import seed
from validacion.contracts import Operacion, Rol
from validacion.repositorio import Repositorio


def test_permisos_coinciden_con_el_plan() -> None:
    permitidas: dict[Rol, set[Operacion]] = {Rol.ASESOR: set(), Rol.SUPERVISOR: set()}
    for rol, operacion in seed.PERMISOS:
        permitidas[rol].add(operacion)
    assert permitidas[Rol.ASESOR] == {Operacion.COTIZAR, Operacion.CONSULTAR_POLIZA}
    assert permitidas[Rol.SUPERVISOR] == {
        Operacion.COTIZAR,
        Operacion.CONSULTAR_POLIZA,
        Operacion.APROBAR_POLIZA,
    }


def test_autorizaciones_coinciden_con_el_plan() -> None:
    ids = [eid for eid, _, _ in seed.AUTORIZACIONES]
    assert len(ids) == 13
    assert ids[:10] == [f"E-ASN-{n:02d}" for n in range(1, 11)]
    assert ids[10:12] == ["E-ASM-01", "E-ASM-02"]
    assert ids[12] == "E-SUP-01"

    por_id = {eid: (rol, alcance) for eid, rol, alcance in seed.AUTORIZACIONES}
    for eid in ids[:10]:
        rol, alcance = por_id[eid]
        assert rol is Rol.ASESOR
        assert alcance == ("norte",)
    for eid in ("E-ASM-01", "E-ASM-02"):
        rol, alcance = por_id[eid]
        assert rol is Rol.ASESOR
        assert alcance == ("norte", "centro")
    rol_sup, alcance_sup = por_id["E-SUP-01"]
    assert rol_sup is Rol.SUPERVISOR
    assert alcance_sup == ("norte", "sur", "centro")


def test_semilla_es_idempotente(tmp_path: Path) -> None:
    repositorio = Repositorio(tmp_path / "v.db")
    repositorio.inicializar()

    assert seed.sembrar(repositorio) == 13
    assert repositorio.contar_permisos() == 5
    assert repositorio.contar_autorizaciones() == 13

    assert seed.sembrar(repositorio) == 0
    assert repositorio.contar_permisos() == 5
    assert repositorio.contar_autorizaciones() == 13


def test_semilla_fija_el_canal_otp_simulado(tmp_path: Path) -> None:
    repositorio = Repositorio(tmp_path / "v.db")
    repositorio.inicializar()
    seed.sembrar(repositorio)

    autorizacion = repositorio.autorizacion("E-ASN-01")
    assert autorizacion is not None
    assert autorizacion.canal_otp == "sim://E-ASN-01"
    assert autorizacion.ultimo_rol_observado is Rol.ASESOR
    assert autorizacion.alcance_autorizado == ["norte"]
