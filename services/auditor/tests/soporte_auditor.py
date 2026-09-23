"""Helpers y dobles de prueba con nombre único en el monorepo.

No viven en `conftest.py` porque cada servicio tiene el suyo y, al correr mypy
desde la raíz, todos resolverían al mismo módulo `conftest`.
"""

import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redis.exceptions import ResponseError

from auditor.cliente_validacion import ErrorValidacionRemota
from auditor.config import Config
from auditor.contracts import CuerpoAnomalia, Decision

STREAM = "auditoria"
GRUPO = "auditor"
EMITIDO = datetime(2026, 9, 21, 14, 2, 10, 418_000, tzinfo=UTC)


def configuracion(tmp_path: Path, **cambios: object) -> Config:
    base: dict[str, object] = {
        "redis_url": "redis://falso",
        "stream_auditoria": STREAM,
        "grupo": GRUPO,
        "consumidor": "auditor-1",
        "periodo_s": 5.0,
        "tamano_lote": 100,
        "url_validacion": "http://validacion.test",
        "timeout_http_ms": 2000,
        "ruta_db": tmp_path / "auditor.db",
        "log_level": "WARNING",
    }
    base.update(cambios)
    return Config(**base)  # type: ignore[arg-type]


class RelojFalso:
    def __init__(self, inicio: datetime = EMITIDO + timedelta(seconds=3)) -> None:
        self.ahora = inicio

    def __call__(self) -> datetime:
        return self.ahora


def evento_dict(
    employee_id: str = "E-ASN-01",
    region: str | None = "sur",
    evento_id: str = "a-1",
    **cambios: Any,
) -> dict[str, Any]:
    """Un `EventoAuditoria` tal como lo serializa gestion-polizas (§4.3)."""
    numero = "003"
    base: dict[str, Any] = {
        "evento_id": evento_id,
        "correlation_id": f"c-{evento_id}",
        "tipo": "operacion.auditada",
        "version": "1",
        "emitido_en": "2026-09-21T14:02:10.418Z",
        "actor": {"employee_id": employee_id, "session_id": f"s-{employee_id}", "rol": "asesor"},
        "accion": "CONSULTA_POLIZA",
        "recurso": {
            "tipo": "poliza",
            "poliza_id": f"POL-{(region or 'nor')[:3].upper()}-{numero}",
            "region": region,
            "cliente_id": None if region is None else f"CLI-{region[:3].upper()}-{numero}",
        },
        "resultado": "OK" if region is not None else "NO_ENCONTRADA",
    }
    base.update(cambios)
    return base


def campos(evento: dict[str, Any]) -> dict[str, str]:
    return {"data": json.dumps(evento, ensure_ascii=False)}


class RedisStreamsFalso:
    """Doble en memoria de un stream con consumer groups: lo justo para el
    patrón de `ciclo.py` (`0` relee pendientes propios; `>` entrega nuevos)."""

    def __init__(self) -> None:
        self._mensajes: list[tuple[str, dict[str, str]]] = []
        self._grupos: set[tuple[str, str]] = set()
        self._posicion: dict[tuple[str, str], int] = {}
        self._pendientes: dict[tuple[str, str], list[str]] = {}
        self._siguiente_id = 1
        self.lecturas: list[tuple[str, int | None, int | None]] = []

    def xadd(self, stream: str, campos: dict[str, str]) -> str:
        mensaje_id = f"{self._siguiente_id}-0"
        self._siguiente_id += 1
        self._mensajes.append((mensaje_id, campos))
        return mensaje_id

    def xgroup_create(
        self,
        name: str,
        groupname: str,
        id: str = "$",  # noqa: A002 -- nombre fijado por la API de Redis
        mkstream: bool = False,
    ) -> bool:
        clave = (name, groupname)
        if clave in self._grupos:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        self._grupos.add(clave)
        self._posicion[clave] = len(self._mensajes) if id == "$" else 0
        self._pendientes[clave] = []
        return True

    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        resultado: list[tuple[str, list[tuple[str, dict[str, str]]]]] = []
        limite = count if count is not None else len(self._mensajes)
        for stream, desde in streams.items():
            self.lecturas.append((desde, count, block))
            clave = (stream, groupname)
            if clave not in self._grupos:
                raise ResponseError(
                    f"NOGROUP No such key '{stream}' or consumer group '{groupname}'"
                )
            if desde == "0":
                indice = dict(self._mensajes)
                mensajes = [(mid, indice[mid]) for mid in self._pendientes[clave]][:limite]
            else:
                pos = self._posicion[clave]
                mensajes = self._mensajes[pos : pos + limite]
                self._posicion[clave] = pos + len(mensajes)
                self._pendientes[clave].extend(mid for mid, _ in mensajes)
            # Redis real también responde [[stream, []]] cuando no hay
            # pendientes; el ciclo debe tolerar ambas formas.
            resultado.append((stream, mensajes))
        return resultado

    def xack(self, name: str, groupname: str, *ids: str) -> int:
        pendientes = self._pendientes.get((name, groupname), [])
        confirmados = 0
        for mensaje_id in ids:
            if mensaje_id in pendientes:
                pendientes.remove(mensaje_id)
                confirmados += 1
        return confirmados

    def pendientes(self, stream: str = STREAM, grupo: str = GRUPO) -> list[str]:
        return list(self._pendientes.get((stream, grupo), []))

    def sin_leer(self, stream: str = STREAM, grupo: str = GRUPO) -> int:
        return len(self._mensajes) - self._posicion[(stream, grupo)]

    def eliminar_grupo(self, stream: str = STREAM, grupo: str = GRUPO) -> None:
        clave = (stream, grupo)
        self._grupos.discard(clave)
        self._posicion.pop(clave, None)
        self._pendientes.pop(clave, None)


@dataclass
class ValidacionFalsa:
    """Aplica la regla de §5.3 con los alcances de §2.2, o falla a demanda."""

    alcance: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            **{f"E-ASN-{n:02d}": ("norte",) for n in range(1, 11)},
            "E-ASM-01": ("norte", "centro"),
            "E-ASM-02": ("norte", "centro"),
            "E-SUP-01": ("norte", "sur", "centro"),
        }
    )
    fallo: ErrorValidacionRemota | None = None
    llamadas: list[CuerpoAnomalia] = field(default_factory=list)

    def informar_anomalia(self, cuerpo: CuerpoAnomalia) -> Decision:
        self.llamadas.append(cuerpo)
        if self.fallo is not None:
            raise self.fallo
        if cuerpo.employee_id not in self.alcance:
            raise ErrorValidacionRemota("/v1/anomalias respondió 404", definitivo=True)
        dentro = cuerpo.region_consultada in self.alcance[cuerpo.employee_id]
        return Decision.ALERTAR if dentro else Decision.REVOCAR
