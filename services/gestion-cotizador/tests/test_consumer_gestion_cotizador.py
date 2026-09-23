"""`procesar()` con un doble de Redis en memoria.

No se levanta un Redis real: el doble solo implementa el subconjunto que
`consumer.procesar` usa (`pipeline().lpush/expire/execute` y `xack`), y se
pasa a la función con `cast` porque estructuralmente no es un `redis.Redis`
—no hace falta serlo para probar el contrato de este worker.
"""

import json
from typing import Any, cast

import pytest
from redis import Redis
from soporte_gestion_cotizador import configuracion

from gestion_cotizador import consumer
from gestion_cotizador.errors import ErrorValidacion

CAMPO = consumer.CAMPO
CORRELATION_ID = "019a05aa-24a1-753e-b019-a0810d66a3f6"


class _TuberiaFalsa:
    def __init__(self, cliente: _ClienteRedisFalso) -> None:
        self._cliente = cliente
        self._operaciones: list[tuple[str, str, str]] = []

    def __enter__(self) -> _TuberiaFalsa:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def lpush(self, clave: str, valor: str) -> _TuberiaFalsa:
        self._operaciones.append(("lpush", clave, valor))
        return self

    def expire(self, clave: str, ttl: int) -> _TuberiaFalsa:
        self._operaciones.append(("expire", clave, str(ttl)))
        return self

    def execute(self) -> list[Any]:
        resultados: list[Any] = []
        for accion, clave, valor in self._operaciones:
            if accion == "lpush":
                self._cliente.listas.setdefault(clave, []).insert(0, valor)
                resultados.append(1)
            else:
                self._cliente.expiraciones[clave] = int(valor)
                resultados.append(True)
        self._operaciones.clear()
        return resultados


class _ClienteRedisFalso:
    def __init__(self) -> None:
        self.listas: dict[str, list[str]] = {}
        self.expiraciones: dict[str, int] = {}
        self.acks: list[tuple[str, str, str]] = []

    def pipeline(self, transaction: bool = False) -> _TuberiaFalsa:
        return _TuberiaFalsa(self)

    def xack(self, nombre: str, grupo: str, mensaje_id: str) -> int:
        self.acks.append((nombre, grupo, mensaje_id))
        return 1


def _sobre_cotizar(**cambios: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "correlation_id": CORRELATION_ID,
        "tipo": "operacion.solicitada",
        "version": "1",
        "emitido_en": "2026-08-31T12:00:00Z",
        "actor": {"employee_id": "E-ASN-01", "session_id": "s1", "rol": "asesor"},
        "operacion": "cotizar",
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
        "fecha_calculo": "2026-08-31",
    }
    base.update(cambios)
    return base


def test_procesar_cotizacion_valida_responde_ok_y_hace_ack() -> None:
    cliente = _ClienteRedisFalso()
    config = configuracion()
    campos = {CAMPO: json.dumps(_sobre_cotizar())}

    consumer.procesar(cast(Redis, cliente), config, "1-0", campos)

    clave = config.clave_respuestas(CORRELATION_ID)
    respuesta = json.loads(cliente.listas[clave][0])

    assert respuesta["correlation_id"] == CORRELATION_ID
    assert respuesta["tipo"] == "operacion.resuelta"
    assert respuesta["servicio"] == "gestion-cotizador"
    assert respuesta["estado"] == "OK"
    assert respuesta["codigo"] == "OK"
    assert respuesta["error"] is None
    assert respuesta["resultado"]["cotizacion"]["prima_mensual"] == "90348.41"
    assert respuesta["resultado"]["cotizacion"]["prima_anual"] == "1084180.92"
    assert respuesta["resultado"]["cotizacion"]["tarifario_version"] == "2026.02"
    assert respuesta["resultado"]["explicacion"]["edad_calculada"] == 38
    assert cliente.expiraciones[clave] == config.ttl_respuestas_s
    assert cliente.acks == [(config.stream_cotizador, config.grupo, "1-0")]


def test_procesar_operacion_desconocida_responde_validacion() -> None:
    cliente = _ClienteRedisFalso()
    config = configuracion()
    campos = {CAMPO: json.dumps(_sobre_cotizar(operacion="aprobar_poliza"))}

    consumer.procesar(cast(Redis, cliente), config, "2-0", campos)

    clave = config.clave_respuestas(CORRELATION_ID)
    respuesta = json.loads(cliente.listas[clave][0])

    assert respuesta["estado"] == "ERROR"
    assert respuesta["codigo"] == "VALIDACION"
    assert respuesta["resultado"] is None
    assert "operacion" in respuesta["error"]
    assert cliente.acks == [(config.stream_cotizador, config.grupo, "2-0")]


def test_procesar_edad_fuera_de_rango_responde_validacion() -> None:
    cliente = _ClienteRedisFalso()
    config = configuracion()
    sobre = _sobre_cotizar()
    sobre["parametros"]["asegurado"]["fecha_nacimiento"] = "2015-01-01"
    campos = {CAMPO: json.dumps(sobre)}

    consumer.procesar(cast(Redis, cliente), config, "3-0", campos)

    clave = config.clave_respuestas(CORRELATION_ID)
    respuesta = json.loads(cliente.listas[clave][0])

    assert respuesta["codigo"] == "VALIDACION"
    assert "fecha_nacimiento" in respuesta["error"]
    assert cliente.acks == [(config.stream_cotizador, config.grupo, "3-0")]


def test_procesar_campo_fuera_de_contrato_responde_validacion() -> None:
    cliente = _ClienteRedisFalso()
    config = configuracion()
    sobre = _sobre_cotizar()
    sobre["parametros"]["suma_asegurada"] = "1"
    campos = {CAMPO: json.dumps(sobre)}

    consumer.procesar(cast(Redis, cliente), config, "4-0", campos)

    clave = config.clave_respuestas(CORRELATION_ID)
    respuesta = json.loads(cliente.listas[clave][0])

    assert respuesta["codigo"] == "VALIDACION"
    assert "suma_asegurada" in respuesta["error"]


def test_procesar_sin_correlation_id_no_responde_ni_hace_ack() -> None:
    """Sin correlation_id no hay dónde depositar la respuesta: se propaga la
    excepción para que `bucle` deje el mensaje pendiente, como uno corrupto."""
    cliente = _ClienteRedisFalso()
    config = configuracion()
    campos = {CAMPO: json.dumps({"tipo": "operacion.solicitada"})}

    with pytest.raises(ErrorValidacion):
        consumer.procesar(cast(Redis, cliente), config, "5-0", campos)

    assert cliente.listas == {}
    assert cliente.acks == []


def test_asegurar_grupo_es_idempotente() -> None:
    class _ClienteConGrupo(_ClienteRedisFalso):
        def __init__(self) -> None:
            super().__init__()
            self.grupos_creados: list[str] = []

        def xgroup_create(
            self,
            name: str,
            groupname: str,
            id: str = "$",  # noqa: A002 -- nombre exigido por la llamada con keyword en consumer.py
            mkstream: bool = False,
        ) -> bool:
            self.grupos_creados.append(groupname)
            return True

    cliente = _ClienteConGrupo()
    config = configuracion()

    consumer.asegurar_grupo(cast(Redis, cliente), config)

    assert cliente.grupos_creados == [config.grupo]
