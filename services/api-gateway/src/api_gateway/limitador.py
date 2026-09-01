"""Limitación de tasa por socio, en ventana fija de un minuto.

Ventana fija y no token bucket: para proteger el journey de un socio que se
desboca basta con un contador, y un contador es trivial de razonar cuando hay
que explicar por qué se devolvió un 429.

Vive en memoria del proceso. Es correcto con un solo worker de gunicorn, que es
como se despliega; con varias instancias de gateway cada una contaría por su
cuenta y el límite efectivo se multiplicaría. En un despliegue real esto va en
el proxy de borde o en un contador compartido.
"""

import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Decision:
    permitido: bool
    restantes: int
    #: Segundos que faltan para que se abra la siguiente ventana.
    reintentar_en: int


class Limitador:
    def __init__(self, limite_por_minuto: int) -> None:
        self._limite = limite_por_minuto
        self._candado = threading.Lock()
        self._ventanas: dict[str, tuple[int, int]] = {}

    def registrar(self, socio: str, ahora_s: float) -> Decision:
        ventana = int(ahora_s // 60)
        reintentar_en = 60 - int(ahora_s % 60)

        with self._candado:
            actual, cuenta = self._ventanas.get(socio, (ventana, 0))
            if actual != ventana:
                actual, cuenta = ventana, 0
            if cuenta >= self._limite:
                self._ventanas[socio] = (actual, cuenta)
                return Decision(False, 0, reintentar_en)
            cuenta += 1
            self._ventanas[socio] = (actual, cuenta)

            # Poda perezosa: sin ella el diccionario crecería con cada socio que
            # apareciera una vez y no volviera.
            if len(self._ventanas) > 1024:
                self._ventanas = {s: v for s, v in self._ventanas.items() if v[0] == ventana}

        return Decision(True, self._limite - cuenta, reintentar_en)
