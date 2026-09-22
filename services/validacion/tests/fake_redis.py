"""Doble de Redis en memoria: solo lo que Validación usa.

`blpop` no bloquea de verdad: en los tests el mensaje o ya está en la lista
(el worker "ya respondió", precargado con `lpush`) o no está y se simula un
timeout devolviendo `None` de inmediato. No hace falta un timer real para
probar la traducción de errores ni el presupuesto de espera.
"""

from collections import defaultdict


class RedisFalso:
    def __init__(self) -> None:
        self.streams: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.listas: dict[str, list[str]] = defaultdict(list)

    def xadd(
        self,
        name: str,
        fields: dict[str, str],
        maxlen: int | None = None,
        approximate: bool | None = None,
    ) -> str:
        self.streams[name].append(dict(fields))
        return f"{len(self.streams[name])}-0"

    def lpush(self, name: str, *valores: str) -> int:
        lista = self.listas[name]
        for valor in valores:
            lista.insert(0, valor)
        return len(lista)

    def blpop(self, keys: list[str] | str, timeout: float | None = None) -> tuple[str, str] | None:
        claves = keys if isinstance(keys, list) else [keys]
        for clave in claves:
            lista = self.listas.get(clave)
            if lista:
                return clave, lista.pop(0)
        return None

    def delete(self, *keys: str) -> int:
        borradas = 0
        for clave in keys:
            if self.listas.get(clave):
                borradas += 1
            self.listas.pop(clave, None)
        return borradas

    def expire(self, name: str, tiempo: int) -> bool:
        return name in self.listas
