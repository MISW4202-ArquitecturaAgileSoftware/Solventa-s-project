from pathlib import Path

from gestion_polizas import seed
from gestion_polizas.contracts import EstadoPoliza
from gestion_polizas.repositorio import Repositorio


def test_semilla_coincide_con_el_plan() -> None:
    polizas = seed._polizas()
    assert len(polizas) == 60
    assert len({p.poliza_id for p in polizas}) == 60

    for prefijo, region in seed.REGIONES:
        de_la_region = [p for p in polizas if p.poliza_id.startswith(f"POL-{prefijo}-")]
        assert [p.poliza_id for p in de_la_region] == [
            f"POL-{prefijo}-{n:03d}" for n in range(1, 21)
        ]

        pendientes = {p.poliza_id for p in de_la_region if p.estado is EstadoPoliza.PENDIENTE}
        emitidas = {p.poliza_id for p in de_la_region if p.estado is EstadoPoliza.EMITIDA}
        assert pendientes == {f"POL-{prefijo}-{n:03d}" for n in range(1, 11)}
        assert emitidas == {f"POL-{prefijo}-{n:03d}" for n in range(11, 21)}

        assert all(p.region == region for p in de_la_region)
        assert all(p.cliente_id == f"CLI-{prefijo}-{p.poliza_id[-3:]}" for p in de_la_region)

    assert all(p.producto == "vida_hipotecario" for p in polizas)
    assert all(p.aprobada_por is None and p.aprobada_en is None for p in polizas)


def test_semilla_es_idempotente(tmp_path: Path) -> None:
    repositorio = Repositorio(tmp_path / "polizas.db")
    repositorio.inicializar()
    assert seed.sembrar(repositorio) == 60
    assert seed.sembrar(repositorio) == 0
    assert repositorio.contar_polizas() == 60
