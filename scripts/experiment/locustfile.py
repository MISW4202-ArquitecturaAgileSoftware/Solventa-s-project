"""Carga concurrente del experimento (PLAN-IMPLEMENTACION.md §6, F9): la parte
que AAS-H710 exige demostrar bajo concurrencia real, no solo en los escenarios
secuenciales de un único actor de `escenarios.py`.

Se ejecuta headless desde `correr.py`, sin interfaz. Cada respuesta de
`AtacanteRafagaASR31` se anota en el JSONL de `RESULTADOS_JSONL`, que
`metricas.py` interpreta después para calcular la ventana de exposición.
"""

from __future__ import annotations

import itertools
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from locust import HttpUser, between, constant, task
from locust.exception import StopUser

from entorno import (
    PASSWORD,
    POLIZA_NORTE_HABITUAL,
    POLIZAS_SUR_RAFAGA,
    POOL_HABITUAL,
    POOL_RAFAGA_ASR31,
    Empleado,
)

_RUTA_JSONL = Path(os.environ.get("RESULTADOS_JSONL", "/tmp/resultados-locust.jsonl"))
_CANDADO_JSONL = threading.Lock()

_RAIZ = Path(__file__).resolve().parents[2]
_COTIZACION: dict[str, Any] = json.loads(
    (_RAIZ / "docs" / "ejemplos" / "cotizacion.json").read_text(encoding="utf-8")
)

_CICLO_RAFAGA = itertools.cycle(POOL_RAFAGA_ASR31)
_CICLO_HABITUAL = itertools.cycle(POOL_HABITUAL)
_CICLO_POLIZAS_SUR = itertools.cycle(POLIZAS_SUR_RAFAGA)


def _registrar(usuario: str, t: float, estado: int, tipo: str | None) -> None:
    linea = json.dumps(
        {"usuario": usuario, "t": t, "estado": estado, "tipo": tipo}, ensure_ascii=False
    )
    with _CANDADO_JSONL, _RUTA_JSONL.open("a", encoding="utf-8") as archivo:
        archivo.write(linea + "\n")


def _tipo_error(cuerpo: Any) -> str | None:
    if not isinstance(cuerpo, dict):
        return None
    tipo = cuerpo.get("type")
    if not isinstance(tipo, str) or not tipo:
        return None
    return tipo.rstrip("/").rsplit("/", 1)[-1]


def _iniciar_sesion(usuario: HttpUser, empleado: Empleado) -> str | None:
    respuesta = usuario.client.post(
        "/v1/sesiones",
        json={"usuario": empleado.usuario, "password": PASSWORD},
        name="/v1/sesiones",
    )
    if respuesta.status_code != 201:
        return None
    token: str = respuesta.json()["token"]
    return token


class AtacanteRafagaASR31(HttpUser):
    """Cinco atacantes concurrentes (`E-ASN-04`..`08`) consultando pólizas de
    `sur`, fuera de su alcance `[norte]`, a ritmo constante hasta que
    Reacción los revoca."""

    wait_time = constant(0.1)
    fixed_count = 5

    _empleado: Empleado
    _token: str
    _inicio: float

    def on_start(self) -> None:
        self._empleado = next(_CICLO_RAFAGA)
        token = _iniciar_sesion(self, self._empleado)
        if token is None:
            raise StopUser
        self._token = token
        self._inicio = time.perf_counter()

    @task
    def consultar_sur(self) -> None:
        poliza_id = next(_CICLO_POLIZAS_SUR)
        with self.client.get(
            f"/v1/polizas/{poliza_id}",
            headers={"Authorization": f"Bearer {self._token}"},
            name="/v1/polizas/[sur]",
            catch_response=True,
        ) as respuesta:
            # El 401 que revoca al atacante es el resultado esperado de la
            # medición, no un fallo de Locust: si se dejara como "failure",
            # `locust --headless` saldría con código de error y tumbaría la
            # corrida entera por el éxito de la detección.
            respuesta.success()
            transcurrido = time.perf_counter() - self._inicio
            cuerpo = respuesta.json() if respuesta.content else None
            _registrar(
                self._empleado.usuario, transcurrido, respuesta.status_code, _tipo_error(cuerpo)
            )
        if respuesta.status_code == 401:
            raise StopUser


class Habitual(HttpUser):
    """Tráfico de fondo (`E-ASN-09/10`, `supervisor.01`): consultas de la
    propia región y cotizaciones, ninguna fuera de alcance."""

    wait_time = between(0.5, 1.5)
    fixed_count = 3

    _empleado: Empleado
    _token: str

    def on_start(self) -> None:
        self._empleado = next(_CICLO_HABITUAL)
        token = _iniciar_sesion(self, self._empleado)
        if token is None:
            raise StopUser
        self._token = token

    @task(2)
    def consultar_norte(self) -> None:
        self.client.get(
            f"/v1/polizas/{POLIZA_NORTE_HABITUAL}",
            headers={"Authorization": f"Bearer {self._token}"},
            name="/v1/polizas/[norte]",
        )

    @task(1)
    def cotizar(self) -> None:
        self.client.post(
            "/v1/cotizaciones",
            json=_COTIZACION,
            headers={"Authorization": f"Bearer {self._token}"},
            name="/v1/cotizaciones",
        )
