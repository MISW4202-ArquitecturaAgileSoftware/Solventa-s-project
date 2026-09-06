"""Acumuladores de una corrida Locust: latencias crudas y primas erróneas."""

from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any

from gevent.lock import Semaphore

from locust_carga.percentil import percentil

_MUESTRAS_ERRONEAS = 5
_HTTP_SIN_VOTACION = frozenset({"429", "0"})


@dataclass
class MuestraErronea:
    indice: int
    estado_http: int
    latencia_ms: float
    estado_cotizacion: str | None
    prima_entregada: str | None
    prima_esperada: str | None
    erronea: bool = True


class MetricasCorrida:
    """Contadores de una corrida. El lock es gevent-safe bajo Locust."""

    def __init__(self, etiqueta: str, modo: str) -> None:
        self.etiqueta = etiqueta
        self.modo = modo
        self._lock = Semaphore()
        self._inicio = time.perf_counter()
        self.enviadas = 0
        self.latencias: list[float] = []
        self.por_http: dict[str, int] = {}
        self.por_estado: dict[str, int] = {}
        self.primas_erroneas = 0
        self.muestras_erroneas: list[MuestraErronea] = []
        self.fallos_efectivos = 0

    def registrar(
        self,
        *,
        indice: int,
        estado_http: int,
        latencia_ms: float,
        estado_cotizacion: str | None = None,
        prima_entregada: str | None = None,
        prima_esperada: str | None = None,
        erronea: bool = False,
        fallo_efectivo: bool = False,
    ) -> None:
        with self._lock:
            self.enviadas += 1
            clave = str(estado_http)
            self.por_http[clave] = self.por_http.get(clave, 0) + 1
            if estado_cotizacion:
                self.por_estado[estado_cotizacion] = self.por_estado.get(estado_cotizacion, 0) + 1
            if fallo_efectivo and clave not in _HTTP_SIN_VOTACION:
                self.fallos_efectivos += 1
            if estado_http == 200:
                self.latencias.append(latencia_ms)
                if erronea:
                    self.primas_erroneas += 1
                    if len(self.muestras_erroneas) < _MUESTRAS_ERRONEAS:
                        self.muestras_erroneas.append(
                            MuestraErronea(
                                indice=indice,
                                estado_http=estado_http,
                                latencia_ms=latencia_ms,
                                estado_cotizacion=estado_cotizacion,
                                prima_entregada=prima_entregada,
                                prima_esperada=prima_esperada,
                            )
                        )

    def resumen(self) -> dict[str, Any]:
        duracion = time.perf_counter() - self._inicio
        latencias = self.latencias
        alcanzaron = sum(
            n for codigo, n in self.por_http.items() if codigo not in _HTTP_SIN_VOTACION
        )
        tasa = round(self.enviadas / duracion * 60, 1) if duracion > 0 else 0.0
        return {
            "etiqueta": self.etiqueta,
            "enviadas": self.enviadas,
            "duracion_s": round(duracion, 1),
            "tasa_real_por_minuto": tasa,
            "por_http": dict(self.por_http),
            "por_estado_cotizacion": dict(self.por_estado),
            "alcanzaron_votacion": alcanzaron,
            "fallos_efectivos": self.fallos_efectivos,
            "latencia_ms": {
                "n": len(latencias),
                "p50": round(percentil(latencias, 0.50), 2),
                "p95": round(percentil(latencias, 0.95), 2),
                "p99": round(percentil(latencias, 0.99), 2),
                "max": round(max(latencias), 2) if latencias else 0,
                "media": round(statistics.mean(latencias), 2) if latencias else 0,
            },
            "primas_erroneas": self.primas_erroneas,
            "muestras_erroneas": [asdict(muestra) for muestra in self.muestras_erroneas],
        }
