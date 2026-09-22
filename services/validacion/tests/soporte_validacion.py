"""Helpers y dobles de prueba con nombre único en el monorepo.

No viven en `conftest.py` porque cada servicio tiene el suyo y, al correr mypy
desde la raíz, todos resolverían al mismo módulo `conftest`.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redis.exceptions import ResponseError

from validacion.cliente_autenticacion import (
    ErrorContencion,
    ResultadoBloqueo,
    ResultadoRevocacion,
)
from validacion.config import Config
from validacion.contracts import ahora_utc, iso_utc_ms


def configuracion(tmp_path: Path, **cambios: object) -> Config:
    base: dict[str, object] = {
        "ruta_db": tmp_path / "validacion.db",
        "redis_url": "redis://falso",
        "stream_polizas": "sol:polizas",
        "stream_cotizador": "sol:cotizador",
        "prefijo_respuestas": "resp",
        "stream_seguridad": "seguridad",
        "stream_maxlen": 10000,
        "timeout_respuesta_ms": 50,
        "modo_experimento": True,
        "log_level": "WARNING",
        # El hilo de Reacción se apaga en los tests: el consumidor se ejercita
        # de forma síncrona con `reaccion.una_vuelta`.
        "reaccion_activa": False,
        "url_autenticacion": "http://autenticacion.test",
        "timeout_http_ms": 2000,
        "grupo_reaccion": "reaccion",
        "consumidor_reaccion": "consumidor-1",
        "block_ms": 1000,
    }
    base.update(cambios)
    return Config(**base)  # type: ignore[arg-type]


class RedisStreamsFalso:
    """Doble en memoria de un stream de Redis con consumer groups.

    Suficiente para el patrón de `reaccion.py`: `xgroup_create`, `xreadgroup`
    (con id `0` para pendientes propios y `>` para mensajes nuevos) y `xack`.
    """

    def __init__(self) -> None:
        self._mensajes: list[tuple[str, dict[str, str]]] = []
        self._grupos: set[tuple[str, str]] = set()
        self._posicion: dict[tuple[str, str], int] = {}
        self._pendientes: dict[tuple[str, str], list[str]] = {}
        self._siguiente_id = 1

    def xadd(self, stream: str, campos: dict[str, str]) -> str:
        mensaje_id = f"{self._siguiente_id}-0"
        self._siguiente_id += 1
        self._mensajes.append((mensaje_id, campos))
        return mensaje_id

    def xgroup_create(
        self,
        name: str,
        groupname: str,
        id: str,  # noqa: A002 -- nombre fijado por la API de Redis
        mkstream: bool = False,
    ) -> None:
        clave = (name, groupname)
        if clave in self._grupos:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        self._grupos.add(clave)
        self._posicion[clave] = len(self._mensajes) if id == "$" else 0
        self._pendientes[clave] = []

    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int = 10,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        resultado: list[tuple[str, list[tuple[str, dict[str, str]]]]] = []
        for stream, desde in streams.items():
            clave = (stream, groupname)
            if clave not in self._grupos:
                raise ResponseError(
                    f"NOGROUP No such key '{stream}' or consumer group '{groupname}'"
                )
            if desde == "0":
                pendientes = self._pendientes[clave]
                indice = dict(self._mensajes)
                mensajes = [(mid, indice[mid]) for mid in pendientes if mid in indice][:count]
            else:
                pos = self._posicion[clave]
                nuevos = self._mensajes[pos : pos + count]
                self._posicion[clave] = pos + len(nuevos)
                self._pendientes[clave].extend(mid for mid, _ in nuevos)
                mensajes = nuevos
            if mensajes:
                resultado.append((stream, mensajes))
        return resultado

    def xack(self, stream: str, groupname: str, mensaje_id: str) -> int:
        clave = (stream, groupname)
        pendientes = self._pendientes.get(clave, [])
        if mensaje_id in pendientes:
            pendientes.remove(mensaje_id)
            return 1
        return 0

    def pendientes(self, stream: str, groupname: str) -> list[str]:
        return list(self._pendientes.get((stream, groupname), []))

    def eliminar_grupo(self, stream: str, groupname: str) -> None:
        clave = (stream, groupname)
        self._grupos.discard(clave)
        self._posicion.pop(clave, None)
        self._pendientes.pop(clave, None)


@dataclass
class ClienteAutenticacionFalso:
    """Registra llamadas y puede fallar de forma transitoria o definitiva."""

    fallo_revocar: ErrorContencion | None = None
    fallo_bloquear: ErrorContencion | None = None
    llamadas: list[tuple[str, ...]] = field(default_factory=list)

    def revocar(
        self, session_id: str, motivo: str, correlation_id: str, evento_id: str
    ) -> ResultadoRevocacion:
        self.llamadas.append(("revocar", session_id, motivo, correlation_id, evento_id))
        if self.fallo_revocar is not None:
            raise self.fallo_revocar
        return ResultadoRevocacion(
            session_id=session_id, revocada_en=iso_utc_ms(ahora_utc()), ya_estaba_revocada=False
        )

    def bloquear(
        self, employee_id: str, motivo: str, correlation_id: str, evento_id: str
    ) -> ResultadoBloqueo:
        self.llamadas.append(("bloquear", employee_id, motivo, correlation_id, evento_id))
        if self.fallo_bloquear is not None:
            raise self.fallo_bloquear
        return ResultadoBloqueo(
            employee_id=employee_id,
            bloqueado_en=iso_utc_ms(ahora_utc()),
            ya_estaba_bloqueado=False,
            sesiones_afectadas=1,
        )


def evento_seguridad_dict(**cambios: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "evento_id": "ev-1",
        "correlation_id": "c-1",
        "tipo": "incidente.detectado",
        "version": "1",
        "emitido_en": "2026-09-21T14:02:12.001Z",
        "employee_id": "E-ASN-01",
        "session_id": "s-1",
        "motivo": "OTP_FALLIDO",
        "accion": "REVOCAR",
        "detalle": {"operacion": "aprobar_poliza", "poliza_id": "POL-NOR-001"},
    }
    base.update(cambios)
    return base
