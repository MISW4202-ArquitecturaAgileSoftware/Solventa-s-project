"""Arranque del Auditor, con apagado limpio ante SIGTERM.

`docker stop` envía SIGTERM y espera. SIGTERM marca un evento que interrumpe
la espera entre ciclos; el ciclo en curso termina y el proceso sale ordenadamente.
"""

import logging
import signal
import sys
import threading
from types import FrameType

from redis import Redis

from auditor import ciclo, seed, structured_logging
from auditor.cliente_validacion import ClienteValidacionHttp
from auditor.config import desde_entorno
from auditor.repositorio import Repositorio

log = logging.getLogger(__name__)


def main() -> int:
    config = desde_entorno()
    structured_logging.configurar("auditor", config.log_level)

    repositorio = Repositorio(config.ruta_db)
    repositorio.inicializar()
    seed.sembrar(repositorio)

    parar = threading.Event()

    def apagar(numero: int, _marco: FrameType | None) -> None:
        log.info("señal recibida, apagando", extra={"senal": signal.Signals(numero).name})
        parar.set()

    signal.signal(signal.SIGTERM, apagar)
    signal.signal(signal.SIGINT, apagar)

    # decode_responses: los eventos son JSON de texto; sin esto llegarían bytes.
    cliente: Redis = Redis.from_url(config.redis_url, decode_responses=True)
    try:
        ciclo.bucle(cliente, config, repositorio, ClienteValidacionHttp(config), parar)
    finally:
        cliente.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
