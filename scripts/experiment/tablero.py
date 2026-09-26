"""Sirve el reporte en vivo en 127.0.0.1.

`correr.py` lo arranca en un hilo al empezar la corrida y el proceso lo
lleva consigo: cuando el experimento termina, el puerto se cierra. La página
pide `/api/estado` una vez por segundo.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import vista

RUTA_PAGINA = Path(__file__).resolve().parent / "tablero.html"
PUERTO_DEFECTO = 8090


def servir(puerto: int, raiz_resultados: Path) -> ThreadingHTTPServer:
    """Abre el puerto en localhost y atiende en un hilo demonio."""
    pagina = RUTA_PAGINA.read_bytes()
    raiz = raiz_resultados

    class Manejador(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            ruta = self.path.split("?", 1)[0]
            if ruta == "/":
                self._bytes(200, "text/html; charset=utf-8", pagina)
                return
            if ruta == "/api/estado":
                self._bytes(
                    200,
                    "application/json; charset=utf-8",
                    json.dumps(_estado(raiz), ensure_ascii=False).encode("utf-8"),
                )
                return
            self._bytes(404, "text/plain; charset=utf-8", b"no encontrado")

        def log_message(self, formato: str, *args: object) -> None:
            return

        def _bytes(self, codigo: int, tipo: str, cuerpo: bytes) -> None:
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)

    ThreadingHTTPServer.allow_reuse_address = True
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    hilo = threading.Thread(target=servidor.serve_forever, name="tablero", daemon=True)
    hilo.start()
    return servidor


def _estado(raiz_resultados: Path) -> dict[str, Any]:
    try:
        return vista.construir_vista(raiz_resultados)
    except Exception as err:
        return {"fase": "error", "detalle": str(err)}


def main(argv: list[str] | None = None) -> int:
    """Arranque manual, para mirar la última corrida con el proceso en primer plano."""
    parser = argparse.ArgumentParser(description="Tablero en vivo del experimento.")
    parser.add_argument("--puerto", type=int, default=PUERTO_DEFECTO)
    parser.add_argument(
        "--resultados",
        type=Path,
        default=Path(__file__).resolve().parent / "resultados",
    )
    args = parser.parse_args(argv)
    servidor = servir(args.puerto, args.resultados)
    print(f"tablero: http://127.0.0.1:{args.puerto}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        servidor.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
