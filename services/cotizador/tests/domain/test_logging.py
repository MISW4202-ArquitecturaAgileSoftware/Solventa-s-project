"""El correlation_id debe aparecer en toda línea de log."""

import json
import logging

from cotizador.common.logging_ import configurar, contexto_correlacion


def test_la_linea_es_json_con_correlation_id(capsys) -> None:  # type: ignore[no-untyped-def]
    configurar("prueba", "INFO")
    with contexto_correlacion("01a05aa8-24a1-753e-b019-a0810d66a3f6"):
        logging.getLogger("x").info("calculada", extra={"cotizador_id": "B"})

    linea = json.loads(capsys.readouterr().out.strip())

    assert linea["correlation_id"] == "01a05aa8-24a1-753e-b019-a0810d66a3f6"
    assert linea["servicio"] == "prueba"
    assert linea["mensaje"] == "calculada"
    assert linea["cotizador_id"] == "B"


def test_fuera_de_contexto_el_correlation_id_es_nulo(capsys) -> None:  # type: ignore[no-untyped-def]
    configurar("prueba", "INFO")
    logging.getLogger("x").info("sin journey")

    linea = json.loads(capsys.readouterr().out.strip())
    assert linea["correlation_id"] is None
