"""El correlation_id debe aparecer en toda línea de log."""

import json
import logging

from gestion_cotizador.structured_logging import configurar, contexto_correlacion


def test_la_linea_es_json_con_correlation_id(capsys) -> None:  # type: ignore[no-untyped-def]
    configurar("prueba", "INFO")
    with contexto_correlacion("019a05aa-24a1-753e-b019-a0810d66a3f6"):
        logging.getLogger("x").info("calculada", extra={"prima_mensual": "90348.41"})

    linea = json.loads(capsys.readouterr().out.strip())

    assert linea["correlation_id"] == "019a05aa-24a1-753e-b019-a0810d66a3f6"
    assert linea["servicio"] == "prueba"
    assert linea["mensaje"] == "calculada"
    assert linea["prima_mensual"] == "90348.41"


def test_fuera_de_contexto_el_correlation_id_es_nulo(capsys) -> None:  # type: ignore[no-untyped-def]
    configurar("prueba", "INFO")
    logging.getLogger("x").info("sin journey")

    linea = json.loads(capsys.readouterr().out.strip())
    assert linea["correlation_id"] is None
