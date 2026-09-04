"""Percentil sobre muestras crudas, comparable con las corridas ya publicadas."""


def percentil(valores: list[float], q: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    return ordenados[min(int(len(ordenados) * q), len(ordenados) - 1)]
