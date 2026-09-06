"""Orquesta el experimento de detección (ASR-11) y enmascaramiento (ASR-12).

Las tres corridas, la inyección de fallos y Locust siguen siendo los mismos
pasos; este módulo los encadena en Python para no pasar números por stdout
entre cinco procesos.

    python scripts/experiment/correr.py
    python scripts/experiment/correr.py --rapido
    python scripts/experiment/correr.py --sin-ui

`RAPIDO=1` y `SIN_UI=1` siguen valiendo, para no romper los comandos ya
documentados. Locust y Docker Compose se invocan como procesos; el resto
(métricas, drenaje, tasa, informe) se importa.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import time
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Timer
from typing import Any, TextIO

import _metricas
import anotar_deteccion
import reporte
import tablero
from locust_carga.drenaje import esperar_metricas_estables

RAIZ = Path(__file__).resolve().parents[2]
RES = RAIZ / "scripts" / "experiment" / "resultados"
LOCUSTFILE = RAIZ / "scripts" / "experiment" / "locustfile.py"
INYECTAR = RAIZ / "scripts" / "experiment" / "inyectar.sh"

MODOS: tuple[str, ...] = (
    "premium_offset",
    "factor_skip",
    "rate_table_stale",
    "rounding_drift",
    "out_of_range",
    "silent_zero",
    "slow",
    "crash",
)

USUARIOS_PICO = 10
# El pacing teórico es 500/min; en la práctica queda ~435. El tope no puede
# ir justo: si Locust termina un segundo después, correr.py aborta sin leer
# el JSON que el SIGTERM acaba de escribir.
MARGEN_S = 90
RITMO_EFECTIVO = 0.8

Inyectar = Callable[[str, str], None]
Cargar = Callable[[str, int, Path, str], None]
Anotar = Callable[[Path, str, int, int], dict[str, Any]]


def cargar_env(ruta: Path) -> None:
    """Carga KEY=VALUE de `.env` sin pisar lo que ya está en el entorno."""
    if not ruta.is_file():
        return
    for cruda in ruta.read_text(encoding="utf-8").splitlines():
        linea = cruda.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        os.environ.setdefault(clave.strip(), valor.strip().strip("'\""))


def tamanos(*, rapido: bool) -> tuple[int, int, int]:
    """n de línea base, por modo de detección y de enmascaramiento."""
    if rapido:
        return 200, 100, 200
    return 5000, 1000, 5000


def segundos_tope(n: int, por_minuto: float) -> int:
    ritmo = max(por_minuto * RITMO_EFECTIVO, 1.0)
    return int(n * 60 / ritmo) + MARGEN_S


def comando_locust(
    *,
    host: str,
    segundos: int,
    sin_ui: bool,
    puerto: int,
    mantener_ui: bool = False,
) -> list[str]:
    comando = [
        "locust",
        "-f",
        str(LOCUSTFILE),
        "--users",
        str(USUARIOS_PICO),
        "--spawn-rate",
        str(USUARIOS_PICO),
        "--host",
        host,
        "--exit-code-on-error",
        "0",
    ]
    if sin_ui:
        comando += ["--run-time", f"{segundos}s", "--headless", "--only-summary"]
    else:
        comando += [
            "--autostart",
            "--web-host",
            "127.0.0.1",
            "--web-port",
            str(puerto),
        ]
        if not mantener_ui:
            comando += ["--run-time", f"{segundos}s", "--autoquit", "0"]
    return comando


def _terminar(proceso: subprocess.Popen[Any]) -> None:
    if proceso.poll() is not None:
        return
    proceso.terminate()
    try:
        proceso.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proceso.kill()


def _salida_lista(ruta: Path) -> bool:
    return ruta.is_file() and ruta.stat().st_size > 0


def _esperar_salida(
    ruta: Path,
    proceso: subprocess.Popen[Any],
    tope_s: float,
    log_locust: Path | None = None,
) -> None:
    inicio = time.perf_counter()
    while time.perf_counter() - inicio < tope_s:
        if _salida_lista(ruta):
            return
        if proceso.poll() is not None:
            break
        time.sleep(0.2)
    # SIGTERM dispara test_stop y Locust escribe el JSON. Hay que esperar a
    # que eso ocurra ANTES de declarar el fallo.
    _terminar(proceso)
    if _salida_lista(ruta):
        return
    extra = f"\n    log: {log_locust}" if log_locust is not None else ""
    if log_locust is not None and log_locust.is_file():
        cola = log_locust.read_text(encoding="utf-8", errors="replace")[-2000:]
        extra += f"\n{cola}"
    raise SystemExit(f"FALLO: Locust no escribió {ruta}{extra}")


def _correr(
    comando: Sequence[str],
    *,
    stdout: int | TextIO | None = None,
    stderr: int | TextIO | None = None,
) -> None:
    subprocess.run(comando, check=True, cwd=RAIZ, stdout=stdout, stderr=stderr)


def inyectar(replica: str, modo: str) -> None:
    _correr([str(INYECTAR), replica, modo])


def restaurar() -> None:
    silenciar: int = subprocess.DEVNULL
    for replica in ("a", "b", "c"):
        _correr([str(INYECTAR), replica, "none"], stdout=silenciar, stderr=silenciar)


def vaciar_evidencia() -> None:
    _correr(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "gestion-errores",
            "sh",
            "-c",
            "> /datos/incidentes.jsonl",
        ]
    )
    _correr(
        ["docker", "compose", "restart", "gestion-errores"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _correr(
        ["docker", "compose", "up", "-d", "--wait"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _abrir_ui(url: str) -> None:
    webbrowser.open(url)


class _Carga:
    def __init__(
        self,
        *,
        sin_ui: bool,
        sin_pausa: bool,
        por_minuto: float,
        puerto: int,
        host: str,
    ) -> None:
        self.sin_ui = sin_ui
        self.sin_pausa = sin_pausa
        self.por_minuto = por_minuto
        self.puerto = puerto
        self.host = host
        self._ui_abierta = False

    def __call__(self, etiqueta: str, n: int, salida: Path, modo: str) -> None:
        segundos = segundos_tope(n, self.por_minuto)
        entorno = os.environ.copy()
        entorno["LOCUST_ETIQUETA"] = etiqueta
        entorno["LOCUST_N"] = str(n)
        entorno["LOCUST_SALIDA"] = str(salida)
        entorno["LOCUST_MODO"] = modo
        entorno["PYTHONUNBUFFERED"] = "1"
        experiment_dir = str(RAIZ / "scripts" / "experiment")
        entorno["PYTHONPATH"] = (
            experiment_dir
            if not entorno.get("PYTHONPATH")
            else experiment_dir + os.pathsep + entorno["PYTHONPATH"]
        )
        mantener_ui = not self.sin_ui and not self.sin_pausa
        if not self.sin_ui:
            url = f"http://127.0.0.1:{self.puerto}"
            print(f"    UI Locust: {url}  ({etiqueta}, modo {modo})")
            if not self._ui_abierta:
                temporizador = Timer(1.0, _abrir_ui, args=(url,))
                temporizador.daemon = True
                temporizador.start()
                self._ui_abierta = True
        comando = comando_locust(
            host=self.host,
            segundos=segundos,
            sin_ui=self.sin_ui,
            puerto=self.puerto,
            mantener_ui=mantener_ui,
        )
        if salida.is_file():
            salida.unlink()
        log_locust = salida.with_name(salida.stem + ".locust.log")
        log = log_locust.open("w", encoding="utf-8")
        proceso = subprocess.Popen(
            comando,
            cwd=RAIZ,
            env=entorno,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            _esperar_salida(salida, proceso, float(segundos + 60), log_locust)
            if mantener_ui:
                print(
                    f"    Gráficos de `{etiqueta}` listos en :{self.puerto}. "
                    "Enter para el siguiente modo…"
                )
                with contextlib.suppress(EOFError):
                    input()
        finally:
            _terminar(proceso)
            log.close()


def corrida_deteccion(
    modos: Sequence[str],
    n: int,
    res: Path,
    *,
    inyectar_fn: Inyectar,
    carga_fn: Cargar,
    leer_total: Callable[[], int],
    esperar: Callable[[], int],
    anotar: Anotar,
    al_empezar: Callable[[str], None] | None = None,
    al_terminar: Callable[[str, dict[str, Any]], None] | None = None,
) -> None:
    """Un modo a la vez: inyecta, carga, drena el reportero y anota la tasa."""
    for modo in modos:
        print(f"--- {modo}")
        if al_empezar is not None:
            al_empezar(modo)
        inyectar_fn("b", modo)
        antes = leer_total()
        ruta = res / f"B-{modo}.json"
        carga_fn(f"deteccion-{modo}", n, ruta, modo)
        despues = esperar()
        datos = anotar(ruta, modo, antes, despues)
        if al_terminar is not None:
            al_terminar(modo, datos)
        tasa = float(datos["tasa_deteccion"]) * 100
        print(
            f"    detectados {datos['incidentes_registrados']}/{datos['fallos_efectivos']} "
            f"= {tasa:.2f}%"
        )


def _parsear(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Orquesta las corridas A/B/C del experimento ASR-11 y ASR-12."
    )
    parser.add_argument(
        "--rapido",
        action="store_true",
        help="versión corta (200/100/200) para depurar",
    )
    parser.add_argument(
        "--sin-ui",
        action="store_true",
        help="Locust headless, sin tablero",
    )
    parser.add_argument(
        "--sin-pausa",
        action="store_true",
        help="no esperar Enter entre modos; Locust se cierra al terminar cada bloque",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    os.chdir(RAIZ)
    cargar_env(RAIZ / ".env")
    args = _parsear(argv)
    rapido = args.rapido or bool(os.environ.get("RAPIDO"))
    sin_ui = args.sin_ui or bool(os.environ.get("SIN_UI"))
    sin_pausa = args.sin_pausa or bool(os.environ.get("SIN_PAUSA"))
    por_minuto = float(os.environ.get("POR_MINUTO", "500"))
    puerto_locust = int(os.environ.get("PUERTO_LOCUST", "8089"))
    puerto_gateway = os.environ.get("PUERTO_GATEWAY", "8000")
    host = f"http://localhost:{puerto_gateway}"

    n_base, n_modo, n_mascara = tamanos(rapido=rapido)
    res = RES
    res.mkdir(parents=True, exist_ok=True)
    for crudo in res.glob("*.json"):
        crudo.unlink()

    panel = tablero.Tablero(res / "estado.json", MODOS)
    puerto_tablero = int(os.environ.get("PUERTO_TABLERO", "8090"))
    if not sin_ui:
        tablero.servir(puerto_tablero, tablero.HTML, res / "estado.json")
        url_tablero = f"http://127.0.0.1:{puerto_tablero}"
        print(f"Tablero de resultados: {url_tablero}")
        temporizador = Timer(0.6, _abrir_ui, args=(url_tablero,))
        temporizador.daemon = True
        temporizador.start()

    carga = _Carga(
        sin_ui=sin_ui,
        sin_pausa=sin_pausa,
        por_minuto=por_minuto,
        puerto=puerto_locust,
        host=host,
    )

    print("### preparación: réplicas sanas y evidencia a cero")
    panel.fase_en("preparación: réplicas sanas y evidencia a cero")
    restaurar()
    vaciar_evidencia()
    print(f"incidentes iniciales: {_metricas.leer()['total']}")

    print()
    print(f"### CORRIDA A — línea base (sin fallo), {n_base} cotizaciones")
    panel.a_en_curso()
    ruta_a = res / "A-baseline.json"
    carga("baseline", n_base, ruta_a, "none")
    panel.registrar_a(json.loads(ruta_a.read_text(encoding="utf-8")))

    print()
    print(f"### CORRIDA B — detección, {n_modo} cotizaciones por modo")
    corrida_deteccion(
        MODOS,
        n_modo,
        res,
        inyectar_fn=inyectar,
        carga_fn=carga,
        leer_total=lambda: int(_metricas.leer()["total"]),
        esperar=esperar_metricas_estables,
        anotar=anotar_deteccion.anotar,
        al_empezar=panel.b_en_curso,
        al_terminar=panel.registrar_b,
    )
    restaurar()

    print()
    print("### CORRIDA C — enmascaramiento sostenido con premium_offset en B")
    panel.c_en_curso()
    inyectar("b", "premium_offset")
    ruta_c = res / "C-enmascaramiento.json"
    carga("enmascaramiento", n_mascara, ruta_c, "premium_offset")
    panel.registrar_c(json.loads(ruta_c.read_text(encoding="utf-8")))
    restaurar()

    print()
    print("### informe")
    panel.fase_en("informe generado")
    codigo = reporte.main()
    if not sin_ui:
        print(f"Tablero: http://127.0.0.1:{puerto_tablero}  (Enter para salir)")
        with contextlib.suppress(EOFError):
            input()
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
