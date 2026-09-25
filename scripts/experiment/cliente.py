"""Cliente HTTP mínimo sobre `requests` para el gateway público y los dos
endpoints de experimento de Autenticación y Validación (PLAN-IMPLEMENTACION.md
§3.2, §3.3, §3.4).

Cada llamada mide su duración con `time.perf_counter()` y recorta el `type` de
RFC 9457 al slug final (p. ej. `.../errors/sesion-revocada` → `sesion-revocada`),
que es como el experimento distingue los distintos `401`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests  # type: ignore[import-untyped]

from entorno import Entorno

TIMEOUT_S = 10.0


@dataclass(frozen=True, slots=True)
class Respuesta:
    estado: int
    tipo_error: str | None
    cuerpo: dict[str, Any]
    duracion_s: float


def _tipo_error(cuerpo: dict[str, Any]) -> str | None:
    tipo = cuerpo.get("type")
    if not isinstance(tipo, str) or not tipo:
        return None
    return tipo.rstrip("/").rsplit("/", 1)[-1]


def _cuerpo_json(respuesta: Any) -> dict[str, Any]:
    try:
        datos = respuesta.json()
    except ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class ClienteExperimento:
    """Sesión HTTP reutilizada por todos los escenarios de una corrida."""

    def __init__(self, entorno: Entorno) -> None:
        self._entorno = entorno
        self._sesion = requests.Session()

    def _llamar(self, metodo: str, url: str, **kwargs: Any) -> Respuesta:
        inicio = time.perf_counter()
        respuesta = self._sesion.request(metodo, url, timeout=TIMEOUT_S, **kwargs)
        duracion = time.perf_counter() - inicio
        cuerpo = _cuerpo_json(respuesta)
        return Respuesta(
            estado=respuesta.status_code,
            tipo_error=_tipo_error(cuerpo),
            cuerpo=cuerpo,
            duracion_s=duracion,
        )

    def login(self, usuario: str, password: str) -> Respuesta:
        url = f"{self._entorno.url_gateway}/v1/sesiones"
        return self._llamar("POST", url, json={"usuario": usuario, "password": password})

    def alterar_rol(self, employee_id: str, rol: str) -> Respuesta:
        """Simula al atacante: `PUT /v1/experimento/empleados/{id}/rol` en
        Autenticación, antes del login para que el JWT ya lleve el rol nuevo."""
        url = f"{self._entorno.url_autenticacion}/v1/experimento/empleados/{employee_id}/rol"
        return self._llamar("PUT", url, json={"rol": rol})

    def leer_otp(self, session_id: str) -> Respuesta:
        """El canal OTP simulado: `GET /v1/experimento/otp/{session_id}` en
        Validación, que solo el empleado legítimo consulta."""
        url = f"{self._entorno.url_validacion}/v1/experimento/otp/{session_id}"
        return self._llamar("GET", url)

    def consultar_poliza(self, token: str, poliza_id: str) -> Respuesta:
        url = f"{self._entorno.url_gateway}/v1/polizas/{poliza_id}"
        return self._llamar("GET", url, headers=_auth(token))

    def aprobar_poliza(self, token: str, poliza_id: str) -> Respuesta:
        url = f"{self._entorno.url_gateway}/v1/polizas/{poliza_id}/aprobacion"
        return self._llamar("POST", url, headers=_auth(token))

    def resolver_otp(self, token: str, codigo: str) -> Respuesta:
        url = f"{self._entorno.url_gateway}/v1/otp"
        return self._llamar("POST", url, json={"codigo": codigo}, headers=_auth(token))

    def cotizar(self, token: str, solicitud: dict[str, Any]) -> Respuesta:
        url = f"{self._entorno.url_gateway}/v1/cotizaciones"
        return self._llamar("POST", url, json=solicitud, headers=_auth(token))
