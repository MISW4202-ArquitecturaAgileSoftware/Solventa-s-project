"""Arranque del worker, con apagado limpio ante SIGTERM.

`docker stop` envía SIGTERM y espera. Si el proceso lo ignora, Docker lo mata
con SIGKILL a los 10 s y el mensaje en curso queda a medias. Aquí SIGTERM marca
un evento; el bucle lo ve al vencer su `block` (≈1 s) y sale ordenadamente.
"""

import logging
import signal
import sys
import threading
from types import FrameType

from redis import Redis

from cotizador import consumer
from cotizador.config import desde_entorno
from solventa_common import logging_

log = logging.getLogger(__name__)


def main() -> int:
    config = desde_entorno()
    logging_.configurar(f"cotizador-{config.cotizador_id.lower()}", config.log_level)

    parar = threading.Event()

    def apagar(numero: int, _marco: FrameType | None) -> None:
        log.info("señal recibida, apagando", extra={"senal": signal.Signals(numero).name})
        parar.set()

    signal.signal(signal.SIGTERM, apagar)
    signal.signal(signal.SIGINT, apagar)

    # decode_responses: el envelope es JSON de texto; sin esto llegarían bytes y
    # cada llamada tendría que decodificar a mano.
    cliente: Redis = Redis.from_url(config.redis_url, decode_responses=True)

    try:
        consumer.bucle(cliente, config, parar)
    finally:
        cliente.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
