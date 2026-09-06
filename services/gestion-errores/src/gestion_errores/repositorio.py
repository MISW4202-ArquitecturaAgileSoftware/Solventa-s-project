"""Persistencia de incidentes en JSONL.

Un fichero de líneas JSON y no una base de datos: la evidencia del experimento
es una secuencia append-only que se lee entera al final de cada corrida.
Introducir un motor de base de datos aquí sería andamiaje sin uso, y añadiría
un servicio más que puede fallar en el camino crítico de la detección.

El fichero es la única fuente de verdad, también para las métricas. Contadores
en memoria darían números distintos según qué worker de gunicorn atendiera la
petición; el fichero no.
"""

import json
import logging
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Metricas:
    total: int
    por_tipo: dict[str, int]
    por_replica: dict[str, int]

    def a_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "por_tipo": self.por_tipo,
            "por_replica_divergente": self.por_replica,
        }


class RepositorioIncidentes:
    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.touch(exist_ok=True)

    def anexar(self, incidente: dict[str, Any]) -> None:
        """Añade una línea y la vuelca a disco.

        El flush es deliberado: sin él, un incidente recién reportado no sería
        visible para /v1/metricas hasta que el buffer del sistema se vaciara, y
        el experimento contaría de menos.
        """
        linea = json.dumps(incidente, ensure_ascii=False, separators=(",", ":"))
        with self.ruta.open("a", encoding="utf-8") as fichero:
            fichero.write(linea + "\n")
            fichero.flush()

    def _leer(self) -> Iterator[dict[str, Any]]:
        with self.ruta.open(encoding="utf-8") as fichero:
            for numero, linea in enumerate(fichero, start=1):
                if not linea.strip():
                    continue
                try:
                    yield json.loads(linea)
                except json.JSONDecodeError:
                    # Una línea truncada (corte de energía a mitad de escritura)
                    # no puede invalidar la lectura de todo el histórico.
                    log.warning("línea ilegible descartada", extra={"linea": numero})

    def por_correlation_id(self, correlation_id: str) -> list[dict[str, Any]]:
        return [i for i in self._leer() if i.get("correlation_id") == correlation_id]

    def todos(self, limite: int | None = None) -> list[dict[str, Any]]:
        incidentes = list(self._leer())
        return incidentes[-limite:] if limite else incidentes

    def metricas(self) -> Metricas:
        """Numerador de ASR-11: cuántas detecciones quedaron registradas."""
        por_tipo: Counter[str] = Counter()
        por_replica: Counter[str] = Counter()
        total = 0
        for incidente in self._leer():
            total += 1
            por_tipo[str(incidente.get("tipo", "desconocido"))] += 1
            for replica in incidente.get("replicas_divergentes") or []:
                por_replica[str(replica)] += 1
        return Metricas(total=total, por_tipo=dict(por_tipo), por_replica=dict(por_replica))
