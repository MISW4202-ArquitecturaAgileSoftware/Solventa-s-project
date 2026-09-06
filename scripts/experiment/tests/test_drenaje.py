"""El drenaje espera silencio en el JSONL, no un sleep ciego."""

from locust_carga.drenaje import esperar_metricas_estables


def test_espera_hasta_que_el_total_deja_de_crecer() -> None:
    lecturas = [1, 2, 2, 2, 2, 2, 2, 2]

    def leer() -> int:
        return lecturas.pop(0) if lecturas else 2

    total = esperar_metricas_estables(
        leer_total=leer,
        silencio_s=0.05,
        tope_s=1.0,
        intervalo_s=0.01,
    )
    assert total == 2


def test_tope_devuelve_el_ultimo_si_sigue_creciendo() -> None:
    n = 0

    def leer() -> int:
        nonlocal n
        n += 1
        return n

    total = esperar_metricas_estables(
        leer_total=leer,
        silencio_s=10.0,
        tope_s=0.12,
        intervalo_s=0.04,
    )
    assert total >= 1
