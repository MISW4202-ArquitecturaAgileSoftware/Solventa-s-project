"""Estado que `correr.py` publica en cada paso para el tablero en vivo.

El archivo `estado.json` de la corrida y el puntero `actual.json` se
reemplazan en un solo `rename`, así el tablero nunca lee un JSON a medias.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import metricas

PASOS: tuple[tuple[str, str], ...] = (
    ("reinicio", "Reinicio del stack"),
    ("atacante_asr23", "Atacante ASR-23"),
    ("legitimo_asr23", "Legítimo ASR-23"),
    ("atacante_asr31", "Atacante lento ASR-31"),
    ("legitimo_inusual", "Consulta inusual ASR-31"),
    ("locust", "Ráfaga Locust"),
    ("alertas", "Alertas de Reacción"),
    ("supervisor", "Cierre del supervisor"),
)


def escribir_json(ruta: Path, datos: Mapping[str, Any]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(ruta)


def exito_atacante_asr23(resultado: Mapping[str, Any]) -> bool:
    return (
        resultado.get("estado_aprobacion_1") == 202
        and resultado.get("estado_otp") == 403
        and resultado.get("tipo_error_otp") == "otp-fallido"
        and resultado.get("estado_aprobacion_2") == 401
        and resultado.get("tipo_error_aprobacion_2") == "sesion-revocada"
    )


def exito_legitimo_asr23(resultado: Mapping[str, Any]) -> bool:
    return (
        resultado.get("estado_operacion_resultado") == "APROBADA"
        and resultado.get("estado_otp") == 200
        and resultado.get("estado_consulta_2") == 200
    )


def exito_atacante_asr31(resultado: Mapping[str, Any]) -> bool:
    return (
        resultado.get("estado_consulta_1") == 200
        and resultado.get("estado_consulta_2") == 401
        and resultado.get("tipo_error_consulta_2") == "sesion-revocada"
    )


def exito_legitimo_inusual(resultado: Mapping[str, Any]) -> bool:
    return resultado.get("estado_consulta_1") == 200 and resultado.get("estado_consulta_2") == 200


def exito_rafaga(filas: Sequence[Mapping[str, Any]]) -> bool:
    """Cada atacante que escribió en el JSONL llegó a un `401`."""
    ventanas = metricas.ventana_exposicion_ms_por_usuario(filas)
    return bool(ventanas) and all(ventana is not None for ventana in ventanas.values())


def exito_cierre(estados: Mapping[str, str], esperado: Mapping[str, str]) -> bool:
    return all(estados.get(poliza) == estado for poliza, estado in esperado.items())


class CorridaEnCurso:
    """Una corrida abierta. Cada mutación queda en disco antes de volver."""

    def __init__(
        self,
        directorio: Path,
        periodos: Sequence[int],
        repeticiones: int,
        puntero: Path,
    ) -> None:
        self.directorio = directorio
        self.puntero = puntero
        self.periodos = [int(periodo) for periodo in periodos]
        self.repeticiones = repeticiones
        self.fecha_inicio = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        self.fase = "en_curso"
        self.periodo_actual: int | None = None
        self.repeticion_actual: int | None = None
        self.paso_actual: str | None = None
        self.jsonl: str | None = None
        self.informe: str | None = None
        self.pasos: list[dict[str, str]] = _pasos_pendientes()
        self.guardar()

    def empezar_repeticion(self, periodo: int, repeticion: int) -> None:
        self.periodo_actual = periodo
        self.repeticion_actual = repeticion
        self.paso_actual = None
        self.jsonl = None
        self.pasos = _pasos_pendientes()
        self.guardar()

    def comenzar(self, paso: str, *, jsonl: str | None = None) -> None:
        self.paso_actual = paso
        if jsonl is not None:
            self.jsonl = jsonl
        _marcar(self.pasos, paso, "en_curso", "")
        self.guardar()

    def cerrar(self, paso: str, resultado: str, detalle: str) -> None:
        _marcar(self.pasos, paso, resultado, detalle)
        if self.paso_actual == paso:
            self.paso_actual = None
        self.guardar()

    def terminar(self, informe: str) -> None:
        self.fase = "terminado"
        self.paso_actual = None
        self.informe = informe
        self.guardar()

    def guardar(self) -> None:
        self.directorio.mkdir(parents=True, exist_ok=True)
        escribir_json(self.directorio / "estado.json", self.a_dict())
        escribir_json(self.puntero, {"directorio": str(self.directorio.resolve())})

    def a_dict(self) -> dict[str, Any]:
        return {
            "fase": self.fase,
            "fecha_inicio": self.fecha_inicio,
            "periodos": self.periodos,
            "repeticiones": self.repeticiones,
            "periodo_actual": self.periodo_actual,
            "repeticion_actual": self.repeticion_actual,
            "paso_actual": self.paso_actual,
            "jsonl": self.jsonl,
            "informe": self.informe,
            "pasos": self.pasos,
        }


def _pasos_pendientes() -> list[dict[str, str]]:
    return [
        {"id": identificador, "titulo": titulo, "estado": "pendiente", "detalle": ""}
        for identificador, titulo in PASOS
    ]


def _marcar(pasos: list[dict[str, str]], paso: str, estado: str, detalle: str) -> None:
    for item in pasos:
        if item["id"] == paso:
            item["estado"] = estado
            item["detalle"] = detalle
            return
    raise KeyError(paso)
