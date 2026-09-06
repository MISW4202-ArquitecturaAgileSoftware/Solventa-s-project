"""El oráculo recalcula la prima con la fecha de Votación, no con el reloj."""

import json
from decimal import Decimal
from pathlib import Path

from locust_carga.oraculo import es_prima_erronea, prima_esperada

RAIZ = Path(__file__).resolve().parents[3]
SOLICITUD = json.loads((RAIZ / "docs" / "ejemplos" / "solicitud.json").read_text(encoding="utf-8"))
CUERPO_SANO = {
    "emitido_en": "2026-08-31T20:41:07.512Z",
    "cotizacion": {"prima_mensual": "90348.41"},
}


def test_oraculo_solicitud_ejemplo() -> None:
    assert prima_esperada(CUERPO_SANO, SOLICITUD) == Decimal("90348.41")
    assert es_prima_erronea(CUERPO_SANO, SOLICITUD) is False


def test_oraculo_detecta_prima_distinta() -> None:
    cuerpo = {
        "emitido_en": CUERPO_SANO["emitido_en"],
        "cotizacion": {"prima_mensual": "1.00"},
    }
    assert es_prima_erronea(cuerpo, SOLICITUD) is True
