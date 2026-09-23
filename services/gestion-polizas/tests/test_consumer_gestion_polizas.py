"""`procesar()` con un doble de Redis en memoria (sin levantar un servidor real)."""

import json
from pathlib import Path
from typing import Any

import pytest

from gestion_polizas.config import Config
from gestion_polizas.consumer import procesar
from gestion_polizas.contracts import ErrorValidacionSobre
from gestion_polizas.repositorio import Repositorio
from gestion_polizas.seed import sembrar


class TuberiaFalsa:
    def __init__(self, cola: ColaFalsa) -> None:
        self._cola = cola
        self._operaciones: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> TuberiaFalsa:
        return self

    def __exit__(self, *_excinfo: object) -> None:
        return None

    def lpush(self, clave: str, valor: str) -> TuberiaFalsa:
        self._operaciones.append(("lpush", (clave, valor)))
        return self

    def expire(self, clave: str, segundos: int) -> TuberiaFalsa:
        self._operaciones.append(("expire", (clave, segundos)))
        return self

    def execute(self) -> list[Any]:
        for nombre, args in self._operaciones:
            if nombre == "lpush":
                clave, valor = args
                self._cola.listas.setdefault(clave, []).insert(0, valor)
            elif nombre == "expire":
                clave, segundos = args
                self._cola.expiraciones[clave] = segundos
        self._operaciones.clear()
        return []


class ColaFalsa:
    """Reemplaza al cliente de Redis: solo lo que `consumer` necesita de él."""

    def __init__(self) -> None:
        self.listas: dict[str, list[str]] = {}
        self.expiraciones: dict[str, int] = {}
        self.eventos: list[tuple[str, dict[str, str]]] = []
        self.acks: list[tuple[str, str, str]] = []

    def pipeline(self, transaction: bool = True) -> TuberiaFalsa:
        del transaction
        return TuberiaFalsa(self)

    def xadd(
        self,
        name: str,
        fields: dict[str, str],
        id: str = "*",  # noqa: A002 -- mismo nombre y posición que redis-py
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        del id, maxlen, approximate
        self.eventos.append((name, fields))
        return "0-1"

    def xack(self, name: str, groupname: str, *ids: str) -> int:
        self.acks.append((name, groupname, ids[0] if ids else ""))
        return 1

    def xgroup_create(
        self,
        name: str,
        groupname: str,
        id: str = "$",  # noqa: A002 -- mismo nombre que `redis-py` y que el Protocol
        mkstream: bool = False,
    ) -> bool:
        del name, groupname, id, mkstream
        return True

    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        del groupname, consumername, streams, count, block
        return []


def _config(tmp_path: Path) -> Config:
    return Config(
        redis_url="redis://localhost:6379/0",
        stream_polizas="sol:polizas",
        prefijo_respuestas="resp",
        stream_auditoria="auditoria",
        stream_maxlen=10000,
        ttl_respuestas_s=60,
        ruta_db=tmp_path / "polizas.db",
        grupo="gestion-polizas",
        consumidor="test",
        block_ms=1000,
        log_level="WARNING",
    )


def _sobre_json(operacion: str, poliza_id: str, correlation_id: str = "c1") -> dict[str, str]:
    return {
        "data": json.dumps(
            {
                "correlation_id": correlation_id,
                "tipo": "operacion.solicitada",
                "version": "1",
                "emitido_en": "2026-09-21T00:00:00.000Z",
                "actor": {"employee_id": "E-ASN-01", "session_id": "s1", "rol": "asesor"},
                "operacion": operacion,
                "parametros": {"poliza_id": poliza_id},
            }
        )
    }


def test_procesar_consulta_exitosa_responde_audita_y_confirma(tmp_path: Path) -> None:
    config = _config(tmp_path)
    repositorio = Repositorio(config.ruta_db)
    repositorio.inicializar()
    sembrar(repositorio)
    cliente = ColaFalsa()

    procesar(cliente, config, repositorio, "1-0", _sobre_json("consultar_poliza", "POL-SUR-003"))

    respuestas = cliente.listas["resp:c1"]
    assert len(respuestas) == 1
    sobre_respuesta = json.loads(respuestas[0])
    assert sobre_respuesta["estado"] == "OK"
    assert sobre_respuesta["codigo"] == "OK"
    assert sobre_respuesta["servicio"] == "gestion-polizas"
    assert sobre_respuesta["resultado"]["region"] == "sur"
    assert cliente.expiraciones["resp:c1"] == 60

    assert len(cliente.eventos) == 1
    stream, campos_evento = cliente.eventos[0]
    assert stream == "auditoria"
    evento = json.loads(campos_evento["data"])
    assert evento["accion"] == "CONSULTA_POLIZA"
    assert evento["recurso"]["region"] == "sur"
    assert evento["recurso"]["cliente_id"] == "CLI-SUR-003"
    assert evento["resultado"] == "OK"
    assert "prima_mensual" not in json.dumps(evento)
    assert "suma_asegurada" not in json.dumps(evento)

    assert cliente.acks == [("sol:polizas", "gestion-polizas", "1-0")]


def test_procesar_consulta_inexistente_audita_recurso_sin_region(tmp_path: Path) -> None:
    config = _config(tmp_path)
    repositorio = Repositorio(config.ruta_db)
    repositorio.inicializar()
    sembrar(repositorio)
    cliente = ColaFalsa()

    procesar(cliente, config, repositorio, "1-0", _sobre_json("consultar_poliza", "POL-SUR-999"))

    sobre_respuesta = json.loads(cliente.listas["resp:c1"][0])
    assert sobre_respuesta["estado"] == "ERROR"
    assert sobre_respuesta["codigo"] == "NO_ENCONTRADA"

    _, campos_evento = cliente.eventos[0]
    evento = json.loads(campos_evento["data"])
    assert evento["recurso"]["region"] is None
    assert evento["recurso"]["cliente_id"] is None
    assert evento["resultado"] == "NO_ENCONTRADA"
    assert cliente.acks == [("sol:polizas", "gestion-polizas", "1-0")]


def test_procesar_aprobacion_exitosa(tmp_path: Path) -> None:
    config = _config(tmp_path)
    repositorio = Repositorio(config.ruta_db)
    repositorio.inicializar()
    sembrar(repositorio)
    cliente = ColaFalsa()

    procesar(cliente, config, repositorio, "1-0", _sobre_json("aprobar_poliza", "POL-CEN-001"))

    sobre_respuesta = json.loads(cliente.listas["resp:c1"][0])
    assert sobre_respuesta["estado"] == "OK"
    assert sobre_respuesta["resultado"]["estado"] == "APROBADA"
    assert sobre_respuesta["resultado"]["aprobada_por"] == "E-ASN-01"

    _, campos_evento = cliente.eventos[0]
    evento = json.loads(campos_evento["data"])
    assert evento["accion"] == "APROBACION_POLIZA"
    assert evento["resultado"] == "OK"


@pytest.mark.parametrize("campos", [{}, {"data": "no es JSON"}, {"data": "{}"}])
def test_mensaje_corrupto_no_responde_ni_confirma(
    tmp_path: Path, campos: dict[str, str]
) -> None:
    config = _config(tmp_path)
    repositorio = Repositorio(config.ruta_db)
    cliente = ColaFalsa()

    with pytest.raises((KeyError, ValueError, ErrorValidacionSobre)):
        procesar(cliente, config, repositorio, "1-0", campos)

    assert cliente.listas == {}
    assert cliente.eventos == []
    assert cliente.acks == []


def test_fallo_de_auditoria_deja_mensaje_sin_confirmar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    repositorio = Repositorio(config.ruta_db)
    repositorio.inicializar()
    sembrar(repositorio)
    cliente = ColaFalsa()

    def fallar(*_args: Any, **_kwargs: Any) -> str:
        raise ConnectionError("auditoría no disponible")

    monkeypatch.setattr(cliente, "xadd", fallar)
    with pytest.raises(ConnectionError, match="auditoría no disponible"):
        procesar(cliente, config, repositorio, "1-0", _sobre_json("consultar_poliza", "POL-NOR-001"))

    assert cliente.acks == []
    assert cliente.eventos == []
    assert json.loads(cliente.listas["resp:c1"][0])["codigo"] == "OK"


def test_segunda_aprobacion_no_modifica_la_poliza_y_audita_el_rechazo(tmp_path: Path) -> None:
    config = _config(tmp_path)
    repositorio = Repositorio(config.ruta_db)
    repositorio.inicializar()
    sembrar(repositorio)
    cliente = ColaFalsa()

    procesar(cliente, config, repositorio, "1-0", _sobre_json("aprobar_poliza", "POL-NOR-001"))
    primera = repositorio.poliza_por_id("POL-NOR-001")
    procesar(
        cliente, config, repositorio, "2-0", _sobre_json("aprobar_poliza", "POL-NOR-001", "c2")
    )

    assert repositorio.poliza_por_id("POL-NOR-001") == primera
    assert json.loads(cliente.listas["resp:c2"][0])["codigo"] == "ESTADO_INVALIDO"
    evento = json.loads(cliente.eventos[-1][1]["data"])
    assert evento["accion"] == "APROBACION_POLIZA"
    assert evento["resultado"] == "ESTADO_INVALIDO"
    assert evento["correlation_id"] == "c2"
    assert len(cliente.acks) == 2
