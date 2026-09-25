from auditor import seed
from auditor.repositorio import Repositorio


def test_semilla_coherente_con_plan_2_2(repositorio: Repositorio) -> None:
    insertadas = seed.sembrar(repositorio)
    assert insertadas == 15

    for n in range(1, 11):
        entrada = repositorio.entrada(f"E-ASN-{n:02d}", "norte")
        assert entrada is not None
        assert entrada.conteo == 1
        assert entrada.primera_vez == entrada.ultima_vez

    for n in range(1, 3):
        assert repositorio.tiene_region(f"E-ASM-{n:02d}", "norte")

    for region in ("norte", "sur", "centro"):
        assert repositorio.tiene_region("E-SUP-01", region)

    assert not repositorio.tiene_region("E-ASN-01", "sur")
    assert not repositorio.tiene_region("E-ASM-01", "centro")


def test_semilla_es_idempotente(repositorio: Repositorio) -> None:
    primera = seed.sembrar(repositorio)
    segunda = seed.sembrar(repositorio)
    assert primera == 15
    assert segunda == 0
    assert repositorio.contar_historial() == 15
