"""El percentil usa el mismo índice que las corridas ya publicadas."""

from locust_carga.percentil import percentil


def test_percentil_vacio() -> None:
    assert percentil([], 0.99) == 0.0


def test_percentil_indice_entero() -> None:
    valores = [1.0, 2.0, 3.0, 4.0, 10.0]
    assert percentil(valores, 0.50) == 3.0
    assert percentil(valores, 0.99) == 10.0
