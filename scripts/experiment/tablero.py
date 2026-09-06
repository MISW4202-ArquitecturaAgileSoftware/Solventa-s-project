"""Tablero vivo del experimento: resultados de A, B y C a medida que salen.

Locust se reinicia en cada bloque y borra sus gráficos. Este tablero es otro
proceso HTTP (puerto 8090) que lee `estado.json` y no se apaga entre modos.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

from reporte import (
    UMBRAL_DETECCION,
    UMBRAL_RETARDO_MS,
    VIA,
    denominador_deteccion,
    ficha_modo,
)

HTML = Path(__file__).with_name("tablero.html")


def _iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


class Tablero:
    """Estado acumulado de las tres corridas. Cada cambio se persiste en JSON."""

    def __init__(self, ruta: Path, modos: tuple[str, ...]) -> None:
        self.ruta = ruta
        self.modos = modos
        self.fase = "inicio"
        self.actualizado = _iso()
        self.a: dict[str, Any] = {"estado": "pendiente"}
        self.b: dict[str, dict[str, Any]] = {
            modo: {"estado": "pendiente", "via": VIA.get(modo, "—")} for modo in modos
        }
        self.c: dict[str, Any] = {"estado": "pendiente"}
        self.escribir()

    def fase_en(self, texto: str) -> None:
        self.fase = texto
        self.escribir()

    def a_en_curso(self) -> None:
        self.a = {"estado": "en_curso", "desde": _iso()}
        self.fase_en("Corrida A · línea base (réplicas sanas)")

    def b_en_curso(self, modo: str) -> None:
        previo = self.b.get(modo, {})
        self.b[modo] = {
            **previo,
            "estado": "en_curso",
            "via": VIA.get(modo, "—"),
            "desde": _iso(),
        }
        self.fase_en(f"Corrida B · detección · {modo} en B")

    def c_en_curso(self) -> None:
        self.c = {"estado": "en_curso", "desde": _iso()}
        self.fase_en("Corrida C · enmascaramiento (premium_offset en B)")

    def registrar_a(self, datos: dict[str, Any]) -> None:
        lat = datos.get("latencia_ms", {})
        self.a = {
            "estado": "hecho",
            "desde": self.a.get("desde"),
            "hasta": _iso(),
            "enviadas": datos.get("enviadas"),
            "tasa": datos.get("tasa_real_por_minuto"),
            "p50": lat.get("p50"),
            "media": lat.get("media"),
            "p99": lat.get("p99"),
            "erroneas": datos.get("primas_erroneas"),
        }
        self.escribir()

    def registrar_b(self, modo: str, datos: dict[str, Any]) -> None:
        tasa = float(datos.get("tasa_deteccion", 0.0))
        previo = self.b.get(modo, {})
        self.b[modo] = {
            "estado": "hecho",
            "via": VIA.get(modo, "—"),
            "desde": previo.get("desde"),
            "hasta": _iso(),
            "fallos_efectivos": denominador_deteccion(datos),
            "alcanzaron_votacion": datos.get("alcanzaron_votacion"),
            "incidentes": datos.get("incidentes_registrados"),
            "tasa": round(tasa * 100, 2),
            "cumple": tasa >= UMBRAL_DETECCION,
            "erroneas": datos.get("primas_erroneas"),
        }
        self.escribir()

    def registrar_c(self, datos: dict[str, Any]) -> None:
        lat = datos.get("latencia_ms", {})
        self.c = {
            "estado": "hecho",
            "desde": self.c.get("desde"),
            "hasta": _iso(),
            "enviadas": datos.get("enviadas"),
            "tasa": datos.get("tasa_real_por_minuto"),
            "p50": lat.get("p50"),
            "media": lat.get("media"),
            "p99": lat.get("p99"),
            "erroneas": datos.get("primas_erroneas"),
            "estados": datos.get("por_estado_cotizacion"),
        }
        self.escribir()

    def a_dict(self) -> dict[str, Any]:
        asr11 = _veredicto_asr11(self.b)
        asr12 = _veredicto_asr12(self.a, self.c)
        return {
            "fase": self.fase,
            "actualizado": self.actualizado,
            "umbral_deteccion": UMBRAL_DETECCION * 100,
            "umbral_retardo_ms": UMBRAL_RETARDO_MS,
            "A": self.a,
            "B": self.b,
            "C": self.c,
            "asr11": asr11,
            "asr12": asr12,
            "catalogo": _catalogo(self.modos, self.b),
            "timeline": _timeline(self.a, self.b, self.c, self.modos, self.actualizado),
        }

    def escribir(self) -> None:
        self.actualizado = _iso()
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text(
            json.dumps(self.a_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _duracion_s(desde: str | None, hasta: str | None) -> float | None:
    if not desde or not hasta:
        return None
    inicio = datetime.fromisoformat(desde)
    fin = datetime.fromisoformat(hasta)
    return round((fin - inicio).total_seconds(), 1)


def _paso_timeline(etiqueta: str, datos: dict[str, Any], ahora: str) -> dict[str, Any]:
    estado = str(datos.get("estado") or "pendiente")
    desde = datos.get("desde")
    hasta = datos.get("hasta") if estado == "hecho" else None
    marca_fin = hasta or (ahora if estado == "en_curso" else None)
    return {
        "etiqueta": etiqueta,
        "estado": estado,
        "desde": desde,
        "hasta": hasta,
        "duracion_s": _duracion_s(desde if isinstance(desde, str) else None, marca_fin),
    }


def _catalogo(modos: tuple[str, ...], bloques: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    fichas: list[dict[str, Any]] = []
    for modo in modos:
        ficha: dict[str, Any] = ficha_modo(modo)
        ficha.update(bloques.get(modo, {}))
        fichas.append(ficha)
    return fichas


def _timeline(
    base: dict[str, Any],
    bloques: dict[str, dict[str, Any]],
    mascara: dict[str, Any],
    modos: tuple[str, ...],
    ahora: str,
) -> list[dict[str, Any]]:
    pasos = [_paso_timeline("A · línea base", base, ahora)]
    pasos.extend(_paso_timeline(f"B · {modo}", bloques.get(modo, {}), ahora) for modo in modos)
    pasos.append(_paso_timeline("C · enmascaramiento", mascara, ahora))
    return pasos


def _veredicto_asr11(bloques: dict[str, dict[str, Any]]) -> dict[str, Any]:
    hechos = [b for b in bloques.values() if b.get("estado") == "hecho"]
    if not hechos:
        return {"estado": "pendiente"}
    tasas = [float(b["tasa"]) for b in hechos]
    peor = min(tasas)
    todos = all(b.get("estado") == "hecho" for b in bloques.values())
    return {
        "estado": "hecho" if todos else "parcial",
        "modos_hechos": len(hechos),
        "modos_total": len(bloques),
        "peor": peor,
        "cumple": todos and peor >= UMBRAL_DETECCION * 100,
    }


def _veredicto_asr12(base: dict[str, Any], mascara: dict[str, Any]) -> dict[str, Any]:
    if base.get("estado") != "hecho" or mascara.get("estado") != "hecho":
        return {"estado": "pendiente"}
    media_a = float(base["media"])
    media_c = float(mascara["media"])
    retardo = round(media_c - media_a, 2)
    erroneas = int(mascara.get("erroneas") or 0)
    return {
        "estado": "hecho",
        "media_a": media_a,
        "media_c": media_c,
        "retardo_ms": retardo,
        "erroneas": erroneas,
        "cumple_latencia": retardo <= UMBRAL_RETARDO_MS,
        "cumple_integridad": erroneas == 0,
        "cumple": retardo <= UMBRAL_RETARDO_MS and erroneas == 0,
    }


def servir(puerto: int, html: Path, estado: Path) -> ThreadingHTTPServer:
    """HTTP mínimo: `/` el HTML, `/estado.json` el snapshot."""

    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, _formato: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            if self.path in {"/", "/index.html"}:
                cuerpo = html.read_bytes()
                self._responder(200, "text/html; charset=utf-8", cuerpo)
                return
            if self.path.startswith("/estado.json"):
                if not estado.is_file():
                    self._responder(404, "application/json", b'{"fase":"sin datos"}')
                    return
                self._responder(200, "application/json; charset=utf-8", estado.read_bytes())
                return
            self._responder(404, "text/plain; charset=utf-8", b"no encontrado")

        def _responder(self, codigo: int, tipo: str, cuerpo: bytes) -> None:
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)

    httpd = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    hilo = Thread(target=httpd.serve_forever, name="tablero", daemon=True)
    hilo.start()
    return httpd
