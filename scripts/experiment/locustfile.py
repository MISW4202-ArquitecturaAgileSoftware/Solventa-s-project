"""Usuario Locust del experimento: horario pico contra el API Gateway.

Diez usuarios con `constant_pacing(1.2)` producen 500 cotizaciones/min, el
ritmo que fija ASR-11. El primer disparo se desfasa entre usuarios para no
salir en ráfaga: sin eso, N pequeñas medirían el hatch y no el pico.

Cualquier respuesta HTTP cuenta como estímulo entregado. Una prima distinta
del oráculo se marca como fallo de Locust: esa es la métrica de ASR-12.
Solo una excepción de red o un cuerpo 200 ilegible se tratan igual.

`LOCUST_N` acota la corrida. `LOCUST_SALIDA` escribe el JSON que consume
`reporte.py`. `LOCUST_MODO` alimenta `prediccion.py`: `fallos_efectivos` solo
cuenta requests que llegaron a Votación y en las que el modo sí inyecta un
error observable.
"""

import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from itertools import count
from pathlib import Path
from threading import Lock
from typing import Any

import gevent
from locust import HttpUser, constant_pacing, events, task
from locust.env import Environment

from locust_carga.metricas_run import MetricasCorrida
from locust_carga.oraculo import prima_esperada
from locust_carga.prediccion import es_fallo_efectivo
from locust_carga.solicitudes import solicitud_de

#: 10 usuarios * 1 request / 1.2 s = 8.33 RPS = 500/min.
PACING_S = 1.2
USUARIOS_PICO = 10
TIMEOUT_S = 5.0


@dataclass
class _Estado:
    hoy: date
    indices: count[int]
    slots: count[int]
    reservadas: int
    limite: int | None
    lock: Lock
    cerrada: bool
    metricas: MetricasCorrida


_estado: _Estado | None = None


def _estado_actual() -> _Estado:
    if _estado is None:
        raise RuntimeError("Locust aún no disparó test_start")
    return _estado


def _iniciar(environment: Environment, **kwargs: object) -> None:
    # Locust dispara el hook con handler(**kwargs); el nombre del argumento
    # tiene que ser exactamente `environment`.
    del environment, kwargs
    global _estado
    crudo = os.environ.get("LOCUST_N")
    _estado = _Estado(
        hoy=datetime.now(tz=UTC).date(),
        indices=count(),
        slots=count(),
        reservadas=0,
        limite=int(crudo) if crudo else None,
        lock=Lock(),
        cerrada=False,
        metricas=MetricasCorrida(
            etiqueta=os.environ.get("LOCUST_ETIQUETA", ""),
            modo=os.environ.get("LOCUST_MODO", "none"),
        ),
    )


def _detener(environment: Environment, **kwargs: object) -> None:
    del environment, kwargs
    if _estado is None:
        return
    resumen = _estado.metricas.resumen()
    print(json.dumps(resumen["latencia_ms"] | {"erroneas": resumen["primas_erroneas"]}))
    salida = os.environ.get("LOCUST_SALIDA")
    if not salida:
        return
    ruta = Path(salida)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")


events.test_start.add_listener(_iniciar)  # type: ignore[no-untyped-call]
events.test_stop.add_listener(_detener)  # type: ignore[no-untyped-call]


def _reservar() -> int | None:
    """Índice de la próxima solicitud, o None si ya se alcanzó LOCUST_N."""
    estado = _estado_actual()
    with estado.lock:
        if estado.limite is not None and estado.reservadas >= estado.limite:
            return None
        estado.reservadas += 1
        return next(estado.indices)


def _cuerpo_json(respuesta: Any) -> dict[str, Any] | None:
    try:
        parsed = respuesta.json()
    except TypeError, ValueError, json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _fecha_calculo(cuerpo: dict[str, Any] | None, respaldo: date) -> date:
    if cuerpo is None:
        return respaldo
    crudo = cuerpo.get("emitido_en")
    if not isinstance(crudo, str):
        return respaldo
    try:
        return datetime.fromisoformat(crudo.replace("Z", "+00:00")).date()
    except ValueError:
        return respaldo


def _latencia_ms(respuesta: Any) -> float:
    meta = getattr(respuesta, "request_meta", None)
    if not isinstance(meta, dict):
        return 0.0
    crudo = meta.get("response_time", 0.0)
    try:
        return float(crudo)
    except TypeError, ValueError:
        return 0.0


class CotizadorUser(HttpUser):
    wait_time = constant_pacing(PACING_S)

    def on_start(self) -> None:
        # Desfasa el primer POST: usuario i espera i * 0.12 s. El POST no va
        # aquí; si fuera, L1 mediría una ráfaga y no el pacing.
        slot = next(_estado_actual().slots) % USUARIOS_PICO
        gevent.sleep(slot * (PACING_S / USUARIOS_PICO))

    @task
    def cotizar(self) -> None:
        indice = _reservar()
        if indice is None:
            estado = _estado_actual()
            with estado.lock:
                ya_cerrada = estado.cerrada
                estado.cerrada = True
            if not ya_cerrada:
                runner = self.environment.runner
                if runner is not None:
                    # Con UI: stop() deja los gráficos. El proceso lo mata
                    # correr.py cuando el operador pulsa Enter.
                    # Headless: quit() termina el proceso.
                    if self.environment.web_ui is not None:
                        runner.stop()
                    else:
                        runner.quit()
            return

        estado = _estado_actual()
        solicitud = solicitud_de(indice, estado.hoy)
        estado_http = 0
        latencia_ms = 0.0
        estado_cotizacion: str | None = None
        prima_entregada: str | None = None
        prima_oraculo: str | None = None
        erronea = False
        cuerpo: dict[str, Any] | None = None

        with self.client.post(
            "/v1/cotizaciones",
            json=solicitud,
            name="cotizar",
            catch_response=True,
            timeout=TIMEOUT_S,
        ) as respuesta:
            estado_http = int(respuesta.status_code or 0)
            latencia_ms = _latencia_ms(respuesta)
            cuerpo = _cuerpo_json(respuesta) if estado_http else None
            if cuerpo is not None:
                crudo_estado = cuerpo.get("estado")
                if isinstance(crudo_estado, str):
                    estado_cotizacion = crudo_estado

            if estado_http == 200 and cuerpo is not None:
                try:
                    esperada = prima_esperada(cuerpo, solicitud)
                    entregada = Decimal(cuerpo["cotizacion"]["prima_mensual"])
                except KeyError, TypeError, ValueError, InvalidOperation:
                    respuesta.failure("cuerpo sin prima verificable")
                else:
                    prima_oraculo = str(esperada)
                    prima_entregada = str(entregada)
                    erronea = entregada != esperada
                    if erronea:
                        respuesta.failure("prima erronea")
                    else:
                        respuesta.success()
            elif estado_http:
                respuesta.success()

        fecha = _fecha_calculo(cuerpo, estado.hoy)
        estado.metricas.registrar(
            indice=indice,
            estado_http=estado_http,
            latencia_ms=latencia_ms,
            estado_cotizacion=estado_cotizacion,
            prima_entregada=prima_entregada,
            prima_esperada=prima_oraculo,
            erronea=erronea,
            fallo_efectivo=es_fallo_efectivo(solicitud, estado.metricas.modo, fecha),
        )
