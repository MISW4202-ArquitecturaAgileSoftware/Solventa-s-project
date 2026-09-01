"""Latido del worker y comando de healthcheck del contenedor.

Un worker no tiene endpoint HTTP, y eso resulta una ventaja: en vez de
comprobar que un servidor web responde, se comprueba que el **bucle consumidor
sigue girando**. El worker refresca `cot:hb:{id}` con TTL corto en cada vuelta;
si el bucle se cuelga, la clave expira y el contenedor se declara enfermo. Un
`/health` de Flask habría seguido respondiendo con el consumidor muerto.
"""

import sys

from redis import Redis

from cotizador.config import Config, desde_entorno


def latir(cliente: Redis, config: Config) -> None:
    """Refresca el latido. Se llama en cada vuelta del bucle, también al vaciarse."""
    cliente.set(config.clave_latido, config.cotizador_id, ex=config.ttl_latido_s)


def esta_sano(cliente: Redis, config: Config) -> bool:
    return bool(cliente.exists(config.clave_latido))


def main() -> int:
    """Punto de entrada del healthcheck del contenedor.

    Devuelve 0 si la réplica está viva y consumiendo, 1 en cualquier otro caso.
    Cualquier excepción (Redis caído, red rota) cuenta como enferma.
    """
    try:
        config = desde_entorno()
        cliente: Redis = Redis.from_url(config.redis_url, socket_timeout=2)
        return 0 if esta_sano(cliente, config) else 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
