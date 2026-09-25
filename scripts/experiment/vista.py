"""Arma el JSON que pinta el tablero, a partir de los archivos de la corrida.

Los criterios y la ventana salen de `reporte.resumen_corridas`, la misma
cuenta que escribe el informe al final. La ráfaga en curso se lee del JSONL
que Locust va agregando, sin esperar a que cierre la repetición.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import metricas
import reporte

_CAMPOS_PASO = ("id", "titulo", "estado", "detalle")


def construir_vista(raiz_resultados: Path) -> dict[str, Any]:
    """Vista de la corrida apuntada por `raiz_resultados/actual.json`.

    Si el puntero no existe, apunta fuera de `raiz_resultados` o el estado
    todavía no está escrito, la respuesta es la de espera: el tablero ya
    puede estar abierto antes de que `correr.py` cree el directorio.
    """
    corrida = _directorio_corrida(raiz_resultados)
    if corrida is None:
        return _esperando()
    estado = _leer_estado(corrida)
    if estado is None:
        return _esperando()

    corridas = _cargar_corridas(corrida)
    resumen = reporte.resumen_corridas(corridas)
    periodos = estado.get("periodos")
    repeticiones = estado.get("repeticiones")
    total = (
        len(periodos) * int(repeticiones)
        if isinstance(periodos, list) and isinstance(repeticiones, int)
        else 0
    )
    fase = estado.get("fase")
    return {
        "fase": fase if fase in {"en_curso", "terminado"} else "en_curso",
        "fecha_inicio": estado.get("fecha_inicio"),
        "periodos": periodos if isinstance(periodos, list) else [],
        "repeticiones": repeticiones if isinstance(repeticiones, int) else 0,
        "corridas_cerradas": len(corridas),
        "corridas_totales": total,
        "periodo_actual": estado.get("periodo_actual"),
        "repeticion_actual": estado.get("repeticion_actual"),
        "paso_actual": estado.get("paso_actual"),
        "pasos": _pasos(estado.get("pasos")),
        "criterios": resumen["criterios"],
        "criterios_definitivos": fase == "terminado",
        "ventana": resumen["ventana"],
        "rafaga": _rafaga(_filas_jsonl(corrida, estado.get("jsonl"))),
        "informe": estado.get("informe") if isinstance(estado.get("informe"), str) else None,
    }


def _esperando() -> dict[str, Any]:
    return {
        "fase": "esperando",
        "fecha_inicio": None,
        "periodos": [],
        "repeticiones": 0,
        "corridas_cerradas": 0,
        "corridas_totales": 0,
        "periodo_actual": None,
        "repeticion_actual": None,
        "paso_actual": None,
        "pasos": [],
        "criterios": [],
        "criterios_definitivos": False,
        "ventana": [],
        "rafaga": [],
        "informe": None,
    }


def _directorio_corrida(raiz_resultados: Path) -> Path | None:
    puntero = raiz_resultados / "actual.json"
    if not puntero.is_file():
        return None
    try:
        datos = json.loads(puntero.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return None
    if not isinstance(datos, dict) or not isinstance(datos.get("directorio"), str):
        return None
    directorio = Path(datos["directorio"]).resolve()
    raiz = raiz_resultados.resolve()
    if not directorio.is_relative_to(raiz) or directorio == raiz:
        return None
    return directorio if directorio.is_dir() else None


def _leer_estado(directorio: Path) -> dict[str, Any] | None:
    ruta = directorio / "estado.json"
    if not ruta.is_file():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return None
    return datos if isinstance(datos, dict) else None


def _cargar_corridas(directorio: Path) -> list[dict[str, Any]]:
    corridas: list[dict[str, Any]] = []
    for ruta in sorted(directorio.glob("p*-r*.json")):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            continue
        if isinstance(datos, dict):
            corridas.append(datos)
    return corridas


def _pasos(crudo: object) -> list[dict[str, str]]:
    if not isinstance(crudo, list):
        return []
    pasos: list[dict[str, str]] = []
    for item in crudo:
        if not isinstance(item, dict):
            continue
        if not all(isinstance(item.get(campo), str) for campo in _CAMPOS_PASO):
            continue
        pasos.append({campo: str(item[campo]) for campo in _CAMPOS_PASO})
    return pasos


def _filas_jsonl(directorio: Path, nombre: object) -> list[dict[str, Any]]:
    """Lee el JSONL de la ráfaga. Ignora la última línea si Locust aún la escribe."""
    if not isinstance(nombre, str) or not nombre or "/" in nombre or nombre.startswith("."):
        return []
    ruta = directorio / nombre
    if not ruta.is_file():
        return []
    filas: list[dict[str, Any]] = []
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError:
        return []
    for linea in texto.splitlines():
        limpia = linea.strip()
        if not limpia:
            continue
        try:
            fila = json.loads(limpia)
        except json.JSONDecodeError:
            continue
        if isinstance(fila, dict):
            filas.append(fila)
    return filas


def _rafaga(filas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not filas:
        return []
    ventanas = metricas.ventana_exposicion_ms_por_usuario(filas)
    consultas = metricas.consultas_200_antes_del_401_por_usuario(filas)
    atacantes: list[dict[str, Any]] = []
    for usuario in sorted(ventanas):
        propias = [fila for fila in filas if str(fila.get("usuario")) == usuario]
        ventana = ventanas[usuario]
        atacantes.append(
            {
                "usuario": usuario,
                "consultas_200": consultas.get(usuario, 0),
                "respuestas_401": sum(1 for fila in propias if fila.get("estado") == 401),
                "ventana_ms": ventana,
                "revocado": ventana is not None,
            }
        )
    return atacantes
