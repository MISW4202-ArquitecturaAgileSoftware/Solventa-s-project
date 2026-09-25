"""Cálculo de los criterios de aceptación de F9 (PLAN-IMPLEMENTACION.md §6, F9).

Funciones puras: no tocan Docker ni la red. `correr.py` recolecta la evidencia
(resultados de escenarios, filas JSONL de Locust, alertas de Reacción —dentro de Validación— y el
conteo de líneas `alerta_duplicada` en sus logs) y `reporte.py` llama estas
funciones para producir la tabla de criterios y la de ventana de exposición.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


def tasa(aciertos: int, total: int) -> float:
    return aciertos / total if total else 1.0


def _percentil(valores: Sequence[float], fraccion: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    if len(ordenados) == 1:
        return ordenados[0]
    posicion = (len(ordenados) - 1) * fraccion
    inferior = int(posicion)
    superior = min(inferior + 1, len(ordenados) - 1)
    peso = posicion - inferior
    return ordenados[inferior] + (ordenados[superior] - ordenados[inferior]) * peso


def percentiles(valores: Sequence[float]) -> tuple[float, float]:
    """p50 y p95 de una muestra de duraciones (mismas unidades que `valores`)."""
    return _percentil(valores, 0.5), _percentil(valores, 0.95)


@dataclass(frozen=True, slots=True)
class CriterioAceptacion:
    metrica: str
    umbral: str
    valor_observado: str
    cumple: bool

    def a_dict(self) -> dict[str, Any]:
        return {
            "metrica": self.metrica,
            "umbral": self.umbral,
            "valor_observado": self.valor_observado,
            "cumple": self.cumple,
        }


def deteccion_otp_fallidos(
    intentos: Sequence[Mapping[str, str]], alertas: Sequence[Mapping[str, Any]]
) -> float:
    """Alertas `OTP_FALLIDO` ÷ intentos inyectados, cruzando por `session_id`."""
    sesiones_alertadas = {a["session_id"] for a in alertas if a.get("motivo") == "OTP_FALLIDO"}
    detectados = sum(1 for intento in intentos if intento["session_id"] in sesiones_alertadas)
    return tasa(detectados, len(intentos))


def operaciones_privilegiadas_ejecutadas(estados_polizas_atacadas: Mapping[str, str]) -> int:
    """Pólizas objetivo que no quedaron `PENDIENTE`: el umbral es 0."""
    return sum(1 for estado in estados_polizas_atacadas.values() if estado != "PENDIENTE")


def segunda_operacion_bloqueada(
    resultados: Sequence[Mapping[str, Any]], campo_estado: str, campo_tipo: str
) -> float:
    """Fracción de escenarios donde la segunda operación/consulta resultó en
    `401 sesion-revocada`."""
    bloqueados = sum(
        1
        for resultado in resultados
        if resultado.get(campo_estado) == 401 and resultado.get(campo_tipo) == "sesion-revocada"
    )
    return tasa(bloqueados, len(resultados))


def latencia_revocacion_p50_p95(latencias_ms: Sequence[float]) -> tuple[float, float]:
    return percentiles(latencias_ms)


def deteccion_alcance_no_autorizado(
    atacantes: Sequence[Mapping[str, str]], alertas: Sequence[Mapping[str, Any]]
) -> float:
    """Alertas `ALCANCE_NO_AUTORIZADO` ÷ empleados atacantes, por `session_id`."""
    sesiones_alertadas = {
        a["session_id"] for a in alertas if a.get("motivo") == "ALCANCE_NO_AUTORIZADO"
    }
    detectados = sum(1 for atacante in atacantes if atacante["session_id"] in sesiones_alertadas)
    return tasa(detectados, len(atacantes))


def falsos_positivos(
    legitimos: Sequence[Mapping[str, str]], alertas: Sequence[Mapping[str, Any]]
) -> int:
    """Alertas con revocación efectiva sobre sesiones legítimas: el umbral es 0."""
    sesiones_legitimas = {legitimo["session_id"] for legitimo in legitimos}
    return sum(
        1
        for alerta in alertas
        if alerta.get("session_id") in sesiones_legitimas and alerta.get("revocada_en") is not None
    )


def alerta_consulta_inusual_presente(
    legitimos: Sequence[Mapping[str, str]], alertas: Sequence[Mapping[str, Any]]
) -> bool:
    sesiones_legitimas = {legitimo["session_id"] for legitimo in legitimos}
    return any(
        alerta.get("session_id") in sesiones_legitimas
        and alerta.get("motivo") == "CONSULTA_INUSUAL"
        for alerta in alertas
    )


def alertas_registradas_duplicadas(alertas: Sequence[Mapping[str, Any]]) -> int:
    """Alertas que comparten `(session_id, motivo)` con otra: el umbral es 0.

    Es distinto del conteo de `alerta_duplicada` en los logs de Validación (Reacción): ese
    mide los eventos redundantes que la idempotencia absorbió, y crece de forma
    legítima cuando un atacante concurrente sigue consultando antes de que la
    revocación surta efecto.
    """
    vistas: set[tuple[str, str]] = set()
    repetidas = 0
    for alerta in alertas:
        clave = (str(alerta.get("session_id")), str(alerta.get("motivo")))
        if clave in vistas:
            repetidas += 1
        vistas.add(clave)
    return repetidas


def _agrupar_por_usuario(
    filas: Sequence[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    por_usuario: dict[str, list[Mapping[str, Any]]] = {}
    for fila in filas:
        por_usuario.setdefault(str(fila["usuario"]), []).append(fila)
    return por_usuario


def ventana_exposicion_ms_por_usuario(
    filas: Sequence[Mapping[str, Any]],
) -> dict[str, float | None]:
    """Milisegundos entre la primera consulta y el primer `401`, por
    `usuario`, a partir de filas `{usuario, t, estado, tipo}` de un JSONL de
    Locust. `None` si ese usuario nunca recibió un `401`."""
    resultado: dict[str, float | None] = {}
    for usuario, filas_usuario in _agrupar_por_usuario(filas).items():
        ordenadas = sorted(filas_usuario, key=lambda f: float(f["t"]))
        t0 = float(ordenadas[0]["t"])
        primer_401 = next((float(f["t"]) for f in ordenadas if f["estado"] == 401), None)
        resultado[usuario] = (primer_401 - t0) * 1000 if primer_401 is not None else None
    return resultado


def intervalo_medio_entre_consultas_ms(filas: Sequence[Mapping[str, Any]]) -> float:
    """Ritmo real del atacante de ráfaga: media de los huecos entre consultas
    consecutivas de un mismo `usuario`, en ms. 0 si no hay huecos."""
    huecos: list[float] = []
    for filas_usuario in _agrupar_por_usuario(filas).values():
        tiempos = sorted(float(f["t"]) for f in filas_usuario)
        huecos.extend((b - a) * 1000 for a, b in zip(tiempos, tiempos[1:], strict=False))
    return sum(huecos) / len(huecos) if huecos else 0.0


def consultas_200_antes_del_401_por_usuario(filas: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Cuántas respuestas `200` recibió cada `usuario` antes de su primer `401`."""
    resultado: dict[str, int] = {}
    for usuario, filas_usuario in _agrupar_por_usuario(filas).items():
        ordenadas = sorted(filas_usuario, key=lambda f: float(f["t"]))
        conteo = 0
        for fila in ordenadas:
            if fila["estado"] == 401:
                break
            if fila["estado"] == 200:
                conteo += 1
        resultado[usuario] = conteo
    return resultado
