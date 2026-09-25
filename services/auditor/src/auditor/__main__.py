"""Arranque del worker, con apagado limpio ante SIGTERM.

`docker stop` envía SIGTERM y espera. Si el proceso lo ignora, Docker lo mata
con SIGKILL a los 10 s y el ciclo en curso queda a medias. Aquí SIGTERM marca
un evento; el bucle lo ve al terminar el ciclo en curso o al vencer la espera
(`threading.Event.wait`) y sale ordenadamente.
"""

import logging
import signal
import sys
import threading
from types import FrameType

from redis import Redis

from auditor import ciclo, seed, structured_logging
from auditor.cliente_validacion import ClienteValidacion
from auditor.config import desde_entorno
from auditor.repositorio import Repositorio

log = logging.getLogger(__name__)


def main() -> int:
    config = desde_entorno()
    structured_logging.configurar("auditor", config.log_level)

    repositorio = Repositorio(config.ruta_db)
    repositorio.inicializar()
    sembrados = seed.sembrar(repositorio)

    parar = threading.Event()

    def apagar(numero: int, _marco: FrameType | None) -> None:
        log.info("señal recibida, apagando", extra={"senal": signal.Signals(numero).name})
        parar.set()

    signal.signal(signal.SIGTERM, apagar)
    signal.signal(signal.SIGINT, apagar)

    # decode_responses: el envelope es JSON de texto; sin esto llegarían bytes
    # y cada llamada tendría que decodificar a mano.
    cliente: Redis = Redis.from_url(config.redis_url, decode_responses=True)
    validacion = ClienteValidacion(config)

    log.info(
        "servicio iniciado",
        extra={"periodo_auditoria_s": config.periodo_auditoria_s, "historial_sembrado": sembrados},
    )

    try:
        ciclo.bucle(cliente, config, repositorio, validacion, parar)
    finally:
        cliente.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
