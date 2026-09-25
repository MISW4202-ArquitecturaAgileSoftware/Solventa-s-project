"""Orquesta el experimento F9 (PLAN-IMPLEMENTACION.md §6, F9): por cada
`PERIODO_AUDITORIA_S` y cada repetición, reinicia el stack con semillas
limpias, corre los cuatro escenarios secuenciales deterministas, lanza la
ráfaga concurrente de Locust, vuelca las alertas de Reacción y guarda toda la
evidencia en JSON. Al final genera `docs/RESULTADOS-EXPERIMENTO.md`.

Un empleado revocado o bloqueado no se puede reutilizar: por eso cada
repetición reinicia el stack (`docker compose down -v && up --wait`), que
resiembra los datos de §2.2 y §2.3.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests  # type: ignore[import-untyped]

import escenarios
import reporte
from cliente import ClienteExperimento
from entorno import (
    ATACANTE_ASR23,
    ATACANTE_ASR31_SECUENCIAL,
    LEGITIMO_ASR23,
    LEGITIMO_INUSUAL_ASR31,
    PASSWORD,
    POLIZA_ATACANTE_ASR23,
    POLIZA_CENTRO_INUSUAL,
    POLIZA_LEGITIMO_ASR23,
    POLIZA_SUR_SECUENCIAL,
    SUPERVISOR,
    Entorno,
    desde_env,
)

RAIZ = Path(__file__).resolve().parents[2]
DIRECTORIO_RESULTADOS = RAIZ / "scripts" / "experiment" / "resultados"
RUTA_REINICIAR = RAIZ / "scripts" / "experiment" / "reiniciar.sh"
RUTA_LOCUSTFILE = RAIZ / "scripts" / "experiment" / "locustfile.py"

#: Margen sobre `3 * periodo_s`: suficiente para un ciclo de auditoría de
#: sobra más la ventana de bloqueo de Reacción, sin alargar la corrida.
DURACION_LOCUST_MARGEN_S = 5
USUARIOS_LOCUST = 8


def _parsear_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Corre el experimento de F9.")
    parser.add_argument("--periodos", default="2,5,10", help="lista separada por comas")
    parser.add_argument("--repeticiones", type=int, default=5)
    parser.add_argument(
        "--rapido", action="store_true", help="equivale a --periodos 2 --repeticiones 1"
    )
    parser.add_argument(
        "--sin-reinicio", action="store_true", help="no reinicia el stack; solo para depurar"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.rapido:
        args.periodos = "2"
        args.repeticiones = 1
    return args


def _reiniciar(periodo: int) -> None:
    entorno_shell = {**os.environ, "PERIODO_AUDITORIA_S": str(periodo)}
    subprocess.run([str(RUTA_REINICIAR)], check=True, cwd=RAIZ, env=entorno_shell)


def _correr_locust(
    entorno: Entorno, periodo: int, ruta_jsonl: Path, prefijo_csv: Path
) -> list[dict[str, Any]]:
    ruta_jsonl.unlink(missing_ok=True)
    duracion_s = 3 * periodo + DURACION_LOCUST_MARGEN_S
    comando = [
        "locust",
        "-f",
        str(RUTA_LOCUSTFILE),
        "--headless",
        "-u",
        str(USUARIOS_LOCUST),
        "-r",
        str(USUARIOS_LOCUST),
        "-t",
        f"{duracion_s}s",
        "--host",
        entorno.url_gateway,
        "--csv",
        str(prefijo_csv),
        "--only-summary",
    ]
    entorno_shell = {**os.environ, "RESULTADOS_JSONL": str(ruta_jsonl)}
    resultado = subprocess.run(comando, cwd=RAIZ, env=entorno_shell)
    if resultado.returncode != 0:
        # Locust sale con código distinto de 0 si `--headless` no pudo
        # arrancar (host inválido, `-f` inexistente…): un fallo real. Pero
        # nuestro propio JSONL, no el código de salida, es la evidencia de si
        # la ráfaga corrió; si el archivo no aparece, sí fue un fallo real.
        print(f"  aviso: locust terminó con código {resultado.returncode}")
    if not ruta_jsonl.is_file():
        return []
    return [
        json.loads(linea)
        for linea in ruta_jsonl.read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]


def _volcar_alertas(entorno: Entorno) -> list[dict[str, Any]]:
    """Alertas registradas por Reacción, que vive dentro de Validación."""
    respuesta = requests.get(f"{entorno.url_validacion}/v1/alertas", timeout=10)
    respuesta.raise_for_status()
    alertas: list[dict[str, Any]] = respuesta.json()["alertas"]
    return alertas


def _contar_alertas_duplicadas() -> int:
    """Eventos redundantes que Reacción absorbió: líneas `alerta_duplicada` en
    los logs de Validación, el contenedor donde corre."""
    resultado = subprocess.run(
        ["docker", "compose", "logs", "validacion", "--no-color"],
        check=True,
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    return resultado.stdout.count('"mensaje": "alerta_duplicada"')


def _verificar_estados_polizas(
    cliente: ClienteExperimento, polizas: Sequence[str]
) -> dict[str, str]:
    login = cliente.login(SUPERVISOR.usuario, PASSWORD)
    token = str(login.cuerpo["token"])
    estados: dict[str, str] = {}
    for poliza_id in polizas:
        respuesta = cliente.consultar_poliza(token, poliza_id)
        estados[poliza_id] = str(respuesta.cuerpo.get("resultado", {}).get("estado"))
    return estados


def _imagenes_docker() -> dict[str, str]:
    resultado = subprocess.run(
        ["docker", "compose", "images", "--format", "json"],
        check=True,
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    filas: list[dict[str, Any]] = json.loads(resultado.stdout) if resultado.stdout.strip() else []
    return {str(fila["Repository"]): str(fila["Tag"]) for fila in filas}


def _correr_repeticion(
    cliente: ClienteExperimento, periodo: int, repeticion: int, directorio: Path
) -> None:
    print("  escenario: atacante ASR-23…")
    resultado_atacante_23 = escenarios.atacante_asr23(
        cliente, ATACANTE_ASR23, POLIZA_ATACANTE_ASR23
    )
    print(
        f"    aprobacion_1={resultado_atacante_23.estado_aprobacion_1} "
        f"otp={resultado_atacante_23.estado_otp}/{resultado_atacante_23.tipo_error_otp} "
        f"aprobacion_2={resultado_atacante_23.estado_aprobacion_2}/"
        f"{resultado_atacante_23.tipo_error_aprobacion_2} "
        f"latencia={resultado_atacante_23.latencia_revocacion_ms:.0f}ms"
    )

    print("  escenario: legítimo ASR-23…")
    resultado_legitimo_23 = escenarios.legitimo_asr23(
        cliente, LEGITIMO_ASR23, POLIZA_LEGITIMO_ASR23
    )
    print(f"    resultado_operacion={resultado_legitimo_23.estado_operacion_resultado}")

    print("  escenario: atacante ASR-31 secuencial…")
    resultado_atacante_31 = escenarios.atacante_asr31_secuencial(
        cliente, ATACANTE_ASR31_SECUENCIAL, POLIZA_SUR_SECUENCIAL, periodo
    )
    print(
        f"    consulta_1={resultado_atacante_31.estado_consulta_1} "
        f"consulta_2={resultado_atacante_31.estado_consulta_2}/"
        f"{resultado_atacante_31.tipo_error_consulta_2}"
    )

    print("  escenario: legítimo inusual ASR-31…")
    resultado_legitimo_31 = escenarios.legitimo_inusual_asr31(
        cliente, LEGITIMO_INUSUAL_ASR31, POLIZA_CENTRO_INUSUAL, periodo
    )
    print(
        f"    consulta_1={resultado_legitimo_31.estado_consulta_1} "
        f"consulta_2={resultado_legitimo_31.estado_consulta_2}"
    )

    print("  Locust: ráfaga ASR-31 concurrente + tráfico habitual…")
    prefijo = f"p{periodo}-r{repeticion}"
    ruta_jsonl = directorio / f"{prefijo}-locust.jsonl"
    filas_locust = _correr_locust(
        desde_env(), periodo, ruta_jsonl, directorio / f"{prefijo}-locust"
    )
    print(f"    {len(filas_locust)} respuestas registradas")

    print("  volcando alertas de Reacción (Validación)…")
    alertas = _volcar_alertas(desde_env())
    duplicadas = _contar_alertas_duplicadas()
    print(f"    {len(alertas)} alertas, {duplicadas} duplicadas en logs")

    print("  verificando estados de pólizas como supervisor…")
    estados_polizas = _verificar_estados_polizas(
        cliente, [POLIZA_ATACANTE_ASR23, POLIZA_LEGITIMO_ASR23]
    )
    print(f"    {estados_polizas}")

    corrida = {
        "periodo_auditoria_s": periodo,
        "repeticion": repeticion,
        "escenarios": {
            "atacante_asr23": dataclasses.asdict(resultado_atacante_23),
            "legitimo_asr23": dataclasses.asdict(resultado_legitimo_23),
            "atacante_asr31_secuencial": dataclasses.asdict(resultado_atacante_31),
            "legitimo_inusual_asr31": dataclasses.asdict(resultado_legitimo_31),
        },
        "locust_filas": filas_locust,
        "alertas": alertas,
        "alertas_duplicadas_en_logs": duplicadas,
        "estados_polizas": estados_polizas,
    }
    ruta_corrida = directorio / f"{prefijo}.json"
    ruta_corrida.write_text(json.dumps(corrida, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parsear_args(argv)
    periodos = [int(p) for p in args.periodos.split(",") if p.strip()]

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    directorio = DIRECTORIO_RESULTADOS / timestamp
    directorio.mkdir(parents=True, exist_ok=True)

    for periodo in periodos:
        for repeticion in range(1, args.repeticiones + 1):
            print(f"=== periodo={periodo}s repeticion={repeticion}/{args.repeticiones} ===")
            if not args.sin_reinicio:
                print("  reiniciando el stack…")
                _reiniciar(periodo)
            cliente = ClienteExperimento(desde_env())
            _correr_repeticion(cliente, periodo, repeticion, directorio)

    print("capturando versiones de imágenes…")
    meta = {
        "fecha": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "periodos": periodos,
        "repeticiones": args.repeticiones,
        "imagenes": _imagenes_docker(),
    }
    (directorio / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("generando informe…")
    ruta_informe = reporte.escribir_informe(directorio)
    print(f"informe escrito en {ruta_informe}")
    print(f"evidencia guardada en {directorio}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
