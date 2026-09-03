"""Envío de incidentes a GestorErrores, fuera del camino crítico.

Votación nunca espera a este envío: se lanza a un pool de hilos justo antes de
devolver la respuesta al cliente. Cada milisegundo gastado aquí saldría del
presupuesto de 300 ms que mide ASR-12, y registrar la evidencia no puede
encarecer el journey que la evidencia describe.

Usa `urllib` de la biblioteca estándar. Un cliente HTTP como `requests` o
`httpx` no aportaría nada para un POST sin reintentos complejos, y se
propagaría a la imagen de todos los servicios que lo compartan.
"""

import json
import logging
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from votacion.contracts import Incidente
from votacion.config import Config

log = logging.getLogger(__name__)


class Reportero:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._pool = ThreadPoolExecutor(
            max_workers=config.hilos_reporte, thread_name_prefix="reportero"
        )

    def reportar(self, incidente: Incidente) -> None:
        """Encola el envío y vuelve de inmediato."""
        self._pool.submit(self._enviar, incidente)

    def _enviar(self, incidente: Incidente) -> None:
        cuerpo = json.dumps(incidente.a_dict(), ensure_ascii=False).encode("utf-8")
        peticion = urllib.request.Request(
            f"{self._config.url_gestion_errores}/v1/incidentes",
            data=cuerpo,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                peticion, timeout=self._config.timeout_reporte_s
            ) as respuesta:
                if respuesta.status != 201:
                    raise RuntimeError(f"estado inesperado {respuesta.status}")
        except (urllib.error.URLError, TimeoutError, RuntimeError) as err:
            # No se reintenta en línea: un GestorErrores caído no puede
            # convertirse en presión sobre Votación. La pérdida queda contada y
            # visible en el log del servicio.
            log.error(
                "no se pudo reportar el incidente",
                extra={
                    "correlation_id": incidente.correlation_id,
                    "motivo": str(err),
                },
            )

    def detener(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=False)
