"""Escritor en segundo plano.

Quien reporta un incidente no debe esperar a que se escriba en disco. Votación
lo llama justo después de haber respondido al cliente, y cualquier milisegundo
que gaste aquí sale del presupuesto de 300 ms que mide ASR-12. Por eso el
endpoint encola y devuelve 202 Accepted, y un hilo dedicado vacía la cola.

La cola es acotada a propósito: si el escritor se atasca, `encolar` falla de
inmediato en lugar de bloquear al que reporta. Perder la evidencia de un
incidente es malo; frenar el journey del cliente para registrarlo es peor, y
además la caída se ve en `pendientes` de /v1/metricas.
"""

import logging
import queue
import threading
from typing import Any

from gestion_errores.repositorio import RepositorioIncidentes

log = logging.getLogger(__name__)

#: Centinela que ordena al hilo terminar tras vaciar lo que quede.
_FIN: Any = object()


class ColaLlenaError(Exception):
    """El escritor no da abasto; el incidente no pudo aceptarse."""


class EscritorIncidentes:
    def __init__(self, repositorio: RepositorioIncidentes, capacidad: int) -> None:
        self._repositorio = repositorio
        self._cola: queue.Queue[Any] = queue.Queue(maxsize=capacidad)
        self._hilo = threading.Thread(target=self._bucle, name="escritor", daemon=True)
        self._perdidos = 0

    def iniciar(self) -> None:
        self._hilo.start()

    def encolar(self, incidente: dict[str, Any]) -> None:
        try:
            self._cola.put_nowait(incidente)
        except queue.Full as err:
            self._perdidos += 1
            raise ColaLlenaError("la cola de incidentes está llena") from err

    @property
    def pendientes(self) -> int:
        """Incidentes aceptados que aún no están en disco.

        El experimento debe esperar a que llegue a cero antes de leer métricas,
        o contaría de menos.
        """
        return self._cola.qsize()

    @property
    def perdidos(self) -> int:
        return self._perdidos

    def esta_vivo(self) -> bool:
        return self._hilo.is_alive()

    def _bucle(self) -> None:
        while True:
            incidente = self._cola.get()
            if incidente is _FIN:
                self._cola.task_done()
                return
            try:
                self._repositorio.anexar(incidente)
            except Exception:
                # Un fallo de escritura no puede matar el hilo: si muriera, el
                # servicio seguiría aceptando 202 y perdiéndolo todo en silencio.
                log.exception("no se pudo persistir el incidente")
            finally:
                self._cola.task_done()

    def detener(self, timeout: float = 5.0) -> None:
        """Vacía lo pendiente y termina. Se llama al apagar el proceso."""
        self._cola.put(_FIN)
        self._hilo.join(timeout=timeout)
