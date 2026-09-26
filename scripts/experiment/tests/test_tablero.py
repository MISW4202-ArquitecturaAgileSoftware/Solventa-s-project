import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import tablero


def test_la_pagina_y_el_estado_siguen_el_jsonl(tmp_path: Path) -> None:
    corrida = tmp_path / "corrida"
    corrida.mkdir()
    (corrida / "estado.json").write_text(
        json.dumps(
            {
                "fase": "en_curso",
                "fecha_inicio": "2026-09-24T00:00:00Z",
                "periodos": [2],
                "repeticiones": 1,
                "periodo_actual": 2,
                "repeticion_actual": 1,
                "paso_actual": "locust",
                "jsonl": "p2-r1-locust.jsonl",
                "informe": None,
                "pasos": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "actual.json").write_text(
        json.dumps({"directorio": str(corrida.resolve())}), encoding="utf-8"
    )
    jsonl = corrida / "p2-r1-locust.jsonl"
    jsonl.write_text(
        json.dumps({"usuario": "asesor.norte.04", "t": 0.0, "estado": 200, "tipo": None}) + "\n",
        encoding="utf-8",
    )

    servidor = tablero.servir(0, tmp_path)
    puerto = int(servidor.server_address[1])
    try:
        with urlopen(f"http://127.0.0.1:{puerto}/") as respuesta:
            pagina = respuesta.read().decode("utf-8")
            assert respuesta.headers["Cache-Control"] == "no-store"
        assert "Solventa — experimento en vivo" in pagina
        assert 'fetch("/api/estado"' in pagina

        with urlopen(f"http://127.0.0.1:{puerto}/api/estado") as respuesta:
            cuerpo = json.loads(respuesta.read().decode("utf-8"))
            assert respuesta.headers["Cache-Control"] == "no-store"
        assert cuerpo["rafaga"][0]["consultas_200"] == 1
        assert cuerpo["fase"] == "en_curso"

        with jsonl.open("a", encoding="utf-8") as archivo:
            archivo.write(
                json.dumps(
                    {
                        "usuario": "asesor.norte.04",
                        "t": 0.3,
                        "estado": 401,
                        "tipo": "sesion-revocada",
                    }
                )
                + "\n"
            )
        with urlopen(f"http://127.0.0.1:{puerto}/api/estado") as respuesta:
            actualizado = json.loads(respuesta.read().decode("utf-8"))
        assert actualizado["rafaga"][0]["respuestas_401"] == 1
        assert actualizado["rafaga"][0]["ventana_ms"] == 300

        try:
            urlopen(f"http://127.0.0.1:{puerto}/no-existe")
        except HTTPError as err:
            assert err.code == 404
        else:
            raise AssertionError("una ruta desconocida debía responder 404")
    finally:
        servidor.shutdown()
        servidor.server_close()
