"""Huella canónica del resultado, base de la comparación entre réplicas.

Votación no compara objetos ni importes campo a campo: compara un `sha256` del
resultado en forma canónica. Eso hace la comparación O(1), exacta y trivial de
registrar en el incidente.

El hash cubre solo lo que debe coincidir entre réplicas sanas. Quedan fuera
`cotizador_id`, `duracion_ms` y cualquier marca de tiempo: varían por réplica
por construcción, e incluirlos haría que ningún par coincidiera nunca.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from votacion.common.contracts import ResultadoCotizacion


def json_canonico(dato: Mapping[str, Any]) -> str:
    """Forma canónica: claves ordenadas, separadores compactos, UTF-8 literal."""
    return json.dumps(
        dato,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def cuerpo_hashable(resultado: ResultadoCotizacion) -> dict[str, Any]:
    """Subconjunto del resultado que debe ser idéntico entre réplicas sanas."""
    return {
        "prima_mensual": str(resultado.prima_mensual),
        "prima_anual": str(resultado.prima_anual),
        "tasa_base_mil": str(resultado.explicacion.tasa_base_mil),
        "factores": resultado.explicacion.factores.a_dict(),
        "tarifario_version": resultado.tarifario_version,
        "edad_calculada": resultado.explicacion.edad_calculada,
    }


def resultado_hash(resultado: ResultadoCotizacion) -> str:
    canonico = json_canonico(cuerpo_hashable(resultado))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()
