"""Prueba automática con el worker y Redis reales, ejecutada dentro del contenedor.

Se envía por stdin con `docker compose exec -T gestion-cotizador python -`.
No requiere Gateway ni Validación y solo elimina sus propias entradas de prueba.
"""

import json
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from redis import Redis
from redis.exceptions import ResponseError

from gestion_cotizador.config import Config, desde_entorno


def esperar(condicion: Callable[[], bool], detalle: str) -> None:
    limite = time.monotonic() + 15
    while time.monotonic() < limite:
        if condicion():
            return
        time.sleep(0.05)
    raise TimeoutError(detalle)


def grupo_listo(cliente: Redis, config: Config) -> bool:
    try:
        grupos: Any = cliente.xinfo_groups(config.stream_cotizador)
    except ResponseError:
        return False
    return any(g["name"] == config.grupo for g in grupos)


def solicitud() -> dict[str, Any]:
    return {
        "correlation_id": str(uuid.uuid7()),
        "tipo": "operacion.solicitada",
        "version": "1",
        "emitido_en": datetime.now(UTC).isoformat(),
        "actor": {"employee_id": "E-ASN-01", "session_id": "prueba", "rol": "asesor"},
        "operacion": "cotizar",
        "fecha_calculo": "2026-08-31",
        "parametros": {
            "producto": "vida_hipotecario",
            "moneda": "COP",
            "suma_asegurada": "250000000.00",
            "plazo_meses": 240,
            "canal": "banco_aliado",
            "asegurado": {
                "fecha_nacimiento": "1988-04-17",
                "genero": "F",
                "fumador": False,
                "clase_ocupacional": 2,
            },
            "consentimiento_open_finance": True,
        },
    }


def comprobar(cliente: Redis, config: Config, sobre: dict[str, Any], codigo: str) -> dict[str, Any]:
    cid = sobre["correlation_id"]
    clave = config.clave_respuestas(cid)
    mid = cliente.xadd(config.stream_cotizador, {"data": json.dumps(sobre)})
    esperar(lambda: bool(cliente.exists(clave)), f"sin respuesta para {cid}")
    esperar(
        lambda: not cliente.xpending_range(config.stream_cotizador, config.grupo, mid, mid, 1),
        f"mensaje sin confirmar: {mid!r}",
    )
    ttl: Any = cliente.ttl(clave)
    assert 0 < ttl <= config.ttl_respuestas_s, f"TTL inválido: {ttl}"
    item: Any = cliente.blpop(clave, timeout=2)
    assert item is not None, "la respuesta desapareció antes de consumirla"
    respuesta: dict[str, Any] = json.loads(item[1])
    assert respuesta["correlation_id"] == cid
    assert respuesta["servicio"] == "gestion-cotizador"
    assert respuesta["codigo"] == codigo, respuesta
    assert respuesta["estado"] == ("OK" if codigo == "OK" else "ERROR")
    cliente.xdel(config.stream_cotizador, mid)
    print(json.dumps({"codigo": codigo, "correlation_id": cid, "ttl": ttl, "ack": True}))
    return respuesta


def main() -> None:
    config = desde_entorno()
    with Redis.from_url(config.redis_url, decode_responses=True) as cliente:
        esperar(lambda: grupo_listo(cliente, config), "el grupo del worker no está listo")
        primera = comprobar(cliente, config, solicitud(), "OK")
        segunda = comprobar(cliente, config, solicitud(), "OK")
        assert primera["resultado"] == segunda["resultado"], "el cálculo no fue determinista"
        assert primera["resultado"]["cotizacion"]["prima_mensual"] == "90348.41"
        assert primera["resultado"]["cotizacion"]["prima_anual"] == "1084180.92"

        operacion_invalida = solicitud() | {"operacion": "aprobar_poliza"}
        comprobar(cliente, config, operacion_invalida, "VALIDACION")
        importe_invalido = solicitud()
        importe_invalido["parametros"]["suma_asegurada"] = "1"
        comprobar(cliente, config, importe_invalido, "VALIDACION")
        print("OK: 4 solicitudes, correlación, cálculo determinista, TTL y XACK verificados")


if __name__ == "__main__":
    main()
