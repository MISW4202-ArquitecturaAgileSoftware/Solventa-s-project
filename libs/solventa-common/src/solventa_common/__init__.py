"""Contratos, tarifario y cálculo compartidos por los microservicios de Solventa.

Todo lo que cruza una frontera entre servicios se define aquí y en ningún otro
sitio. Si un servicio necesita redefinir un contrato, el contrato está mal.
"""

from solventa_common.contracts import (
    Asegurado,
    Canal,
    EstadoCotizacion,
    EstadoRespuesta,
    Explicacion,
    Factores,
    Genero,
    Incidente,
    Moneda,
    Producto,
    ResultadoCotizacion,
    SobreRespuesta,
    SobreSolicitud,
    SolicitudCotizacion,
    TipoIncidente,
    ValorRecibido,
    ahora_utc,
    iso_utc,
)
from solventa_common.errors import (
    ErrorSinConsenso,
    ErrorSocioNoIdentificado,
    ErrorSolventa,
    ErrorTimeoutCotizacion,
    ErrorValidacion,
    TarifarioDesconocido,
    a_problem_json,
)
from solventa_common.hashing import json_canonico, resultado_hash
from solventa_common.ids import es_correlation_id_valido, nuevo_correlation_id
from solventa_common.pricing import (
    Violacion,
    calcular,
    calcular_con_tabla,
    edad_cumplida,
    redondear,
    validar,
)

__all__ = [
    "Asegurado",
    "Canal",
    "ErrorSinConsenso",
    "ErrorSocioNoIdentificado",
    "ErrorSolventa",
    "ErrorTimeoutCotizacion",
    "ErrorValidacion",
    "EstadoCotizacion",
    "EstadoRespuesta",
    "Explicacion",
    "Factores",
    "Genero",
    "Incidente",
    "Moneda",
    "Producto",
    "ResultadoCotizacion",
    "SobreRespuesta",
    "SobreSolicitud",
    "SolicitudCotizacion",
    "TarifarioDesconocido",
    "TipoIncidente",
    "ValorRecibido",
    "Violacion",
    "a_problem_json",
    "ahora_utc",
    "calcular",
    "calcular_con_tabla",
    "edad_cumplida",
    "es_correlation_id_valido",
    "iso_utc",
    "json_canonico",
    "nuevo_correlation_id",
    "redondear",
    "resultado_hash",
    "validar",
]
