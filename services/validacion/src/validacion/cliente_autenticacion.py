"""Cliente HTTP de Autenticación (`urllib` de la biblioteca estándar).

Lo usa el proceso de Reacción para revocar la sesión y bloquear al empleado.
Ambas operaciones son idempotentes en Autenticación (§3.3): un reintento nunca
duplica el efecto. Por eso un 404 (sesión o empleado inexistente) es un fallo
DEFINITIVO —reintentar no lo arregla—, mientras que un error de red, un 5xx o
un timeout son TRANSITORIOS y se reintentan en la siguiente vuelta.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from validacion.config import Config


class ErrorContencion(Exception):
    def __init__(self, mensaje: str, *, definitivo: bool) -> None:
        super().__init__(mensaje)
        self.definitivo = definitivo


@dataclass(frozen=True, slots=True)
class ResultadoRevocacion:
    session_id: str
    revocada_en: str
    ya_estaba_revocada: bool


@dataclass(frozen=True, slots=True)
class ResultadoBloqueo:
    employee_id: str
    bloqueado_en: str
    ya_estaba_bloqueado: bool
    sesiones_afectadas: int


class ClienteAutenticacion(Protocol):
    def revocar(
        self, session_id: str, motivo: str, correlation_id: str, evento_id: str
    ) -> ResultadoRevocacion: ...

    def bloquear(
        self, employee_id: str, motivo: str, correlation_id: str, evento_id: str
    ) -> ResultadoBloqueo: ...


def _texto(cuerpo: dict[str, Any], ruta: str, campo: str) -> str:
    valor = cuerpo.get(campo)
    if not isinstance(valor, str):
        raise ErrorContencion(f"respuesta de {ruta} sin {campo} válido", definitivo=False)
    return valor


def _booleano(cuerpo: dict[str, Any], ruta: str, campo: str) -> bool:
    valor = cuerpo.get(campo)
    if not isinstance(valor, bool):
        raise ErrorContencion(f"respuesta de {ruta} sin {campo} válido", definitivo=False)
    return valor


def _entero(cuerpo: dict[str, Any], ruta: str, campo: str) -> int:
    valor = cuerpo.get(campo)
    if not isinstance(valor, int) or isinstance(valor, bool):
        raise ErrorContencion(f"respuesta de {ruta} sin {campo} válido", definitivo=False)
    return valor


class ClienteAutenticacionHttp:
    def __init__(self, config: Config) -> None:
        self._base = config.url_autenticacion.rstrip("/")
        self._timeout_s = config.timeout_http_ms / 1000

    def revocar(
        self, session_id: str, motivo: str, correlation_id: str, evento_id: str
    ) -> ResultadoRevocacion:
        ruta = f"/v1/sesiones/{session_id}/revocacion"
        cuerpo = self._post(ruta, motivo, correlation_id, evento_id)
        return ResultadoRevocacion(
            session_id=_texto(cuerpo, ruta, "session_id"),
            revocada_en=_texto(cuerpo, ruta, "revocada_en"),
            ya_estaba_revocada=_booleano(cuerpo, ruta, "ya_estaba_revocada"),
        )

    def bloquear(
        self, employee_id: str, motivo: str, correlation_id: str, evento_id: str
    ) -> ResultadoBloqueo:
        ruta = f"/v1/empleados/{employee_id}/bloqueo"
        cuerpo = self._post(ruta, motivo, correlation_id, evento_id)
        return ResultadoBloqueo(
            employee_id=_texto(cuerpo, ruta, "employee_id"),
            bloqueado_en=_texto(cuerpo, ruta, "bloqueado_en"),
            ya_estaba_bloqueado=_booleano(cuerpo, ruta, "ya_estaba_bloqueado"),
            sesiones_afectadas=_entero(cuerpo, ruta, "sesiones_afectadas"),
        )

    def _post(self, ruta: str, motivo: str, correlation_id: str, evento_id: str) -> dict[str, Any]:
        datos = json.dumps(
            {"motivo": motivo, "correlation_id": correlation_id, "evento_id": evento_id},
            ensure_ascii=False,
        ).encode("utf-8")
        peticion = urllib.request.Request(
            f"{self._base}{ruta}",
            data=datos,
            method="POST",
            headers={"Content-Type": "application/json", "X-Correlation-Id": correlation_id},
        )
        try:
            with urllib.request.urlopen(peticion, timeout=self._timeout_s) as respuesta:
                if respuesta.status != 200:
                    raise ErrorContencion(
                        f"{ruta} respondió con estado inesperado {respuesta.status}",
                        definitivo=False,
                    )
                cuerpo = json.loads(respuesta.read())
        except urllib.error.HTTPError as err:
            raise ErrorContencion(
                f"{ruta} respondió {err.code}", definitivo=err.code == 404
            ) from err
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
            raise ErrorContencion(f"fallo de red hacia {ruta}: {err}", definitivo=False) from err
        if not isinstance(cuerpo, dict):
            raise ErrorContencion(f"{ruta} no devolvió un objeto JSON", definitivo=False)
        resultado: dict[str, Any] = cuerpo
        return resultado
