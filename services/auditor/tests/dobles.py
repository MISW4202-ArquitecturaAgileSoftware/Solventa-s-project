"""Dobles de prueba: Redis en memoria y cliente de Validación configurable.

No son mocks genéricos: reproducen justo la semántica de streams y consumer
groups que `ciclo.py` necesita (pendientes propios por `id="0"`, nuevos por
`id=">"`, `NOGROUP`/`BUSYGROUP`), para poder testear el ciclo sin Redis real.
"""

import itertools
from dataclasses import dataclass, field

from redis.exceptions import ResponseError

from auditor.cliente_validacion import ErrorValidacionTransitoria
from auditor.contracts import Decision, EventoAuditoria


class RedisFalso:
    def __init__(self) -> None:
        self._mensajes: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._grupos: set[tuple[str, str]] = set()
        self._proximo: dict[tuple[str, str], int] = {}
        self._pendientes: dict[tuple[str, str, str], dict[str, dict[str, str]]] = {}
        self._contador = itertools.count(1)

    def publicar(self, stream: str, campos: dict[str, str]) -> str:
        mensaje_id = f"{next(self._contador)}-0"
        self._mensajes.setdefault(stream, []).append((mensaje_id, campos))
        return mensaje_id

    def xgroup_create(
        self,
        name: str,
        groupname: str,
        id: str,  # noqa: A002
        mkstream: bool = False,
    ) -> None:
        clave = (name, groupname)
        if clave in self._grupos:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        self._grupos.add(clave)
        self._proximo[clave] = len(self._mensajes.get(name, []))

    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        ((stream, id_lectura),) = streams.items()
        clave_grupo = (stream, groupname)
        if clave_grupo not in self._grupos:
            raise ResponseError("NOGROUP No such key or consumer group")

        clave_consumidor = (stream, groupname, consumername)
        if id_lectura == ">":
            todos = self._mensajes.get(stream, [])
            inicio = self._proximo[clave_grupo]
            limite = len(todos) if count is None else min(len(todos), inicio + count)
            nuevos = todos[inicio:limite]
            self._proximo[clave_grupo] = limite
            pendientes_consumidor = self._pendientes.setdefault(clave_consumidor, {})
            for mensaje_id, campos in nuevos:
                pendientes_consumidor[mensaje_id] = campos
            resultado = nuevos
        else:
            pendientes_consumidor = self._pendientes.get(clave_consumidor, {})
            items = list(pendientes_consumidor.items())
            resultado = items if count is None else items[:count]

        if not resultado:
            return []
        return [(stream, resultado)]

    def xack(self, name: str, groupname: str, id: str) -> int:  # noqa: A002
        for (stream, grupo, _consumidor), pendientes in self._pendientes.items():
            if stream == name and grupo == groupname and id in pendientes:
                del pendientes[id]
                return 1
        return 0

    def close(self) -> None:
        pass


@dataclass
class ValidacionFalsa:
    decisiones: dict[tuple[str, str], Decision] = field(default_factory=dict)
    fallar_para: set[str] = field(default_factory=set)
    desconocidos: set[str] = field(default_factory=set)
    llamadas: list[EventoAuditoria] = field(default_factory=list)

    def informar_anomalia(self, evento: EventoAuditoria) -> Decision:
        self.llamadas.append(evento)
        if evento.actor.employee_id in self.fallar_para:
            raise ErrorValidacionTransitoria("simulado")
        if evento.actor.employee_id in self.desconocidos:
            return Decision.IGNORAR
        region = evento.recurso.region
        assert region is not None
        return self.decisiones.get((evento.actor.employee_id, region), Decision.ALERTAR)
