"""Las dos operaciones de negocio de Gestión de Pólizas, sobre SQLite.

El worker recibe operaciones autorizadas por Validación y no verifica rol
ni alcance de `actor`. El despliegue debe proteger a los productores mediante
aislamiento y permisos sobre Redis; la red por sí sola no restringe las claves.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from gestion_polizas.contracts import (
    AccionAuditoria,
    CodigoRespuesta,
    ErrorValidacionSobre,
    EstadoRespuesta,
    ParametrosPoliza,
    SobreOperacion,
)
from gestion_polizas.repositorio import Repositorio

log = logging.getLogger(__name__)

_ACCION_POR_OPERACION: dict[str, AccionAuditoria] = {
    "consultar_poliza": AccionAuditoria.CONSULTA_POLIZA,
    "aprobar_poliza": AccionAuditoria.APROBACION_POLIZA,
}


@dataclass(frozen=True, slots=True)
class ResultadoOperacion:
    estado: EstadoRespuesta
    codigo: CodigoRespuesta
    accion: AccionAuditoria
    resultado: dict[str, Any] | None = None
    error: str | None = None
    poliza_id: str | None = None
    region: str | None = None
    cliente_id: str | None = None


def ejecutar(
    repositorio: Repositorio, sobre: SobreOperacion, ahora: datetime
) -> ResultadoOperacion:
    # Operación desconocida: no hay una acción real que atribuirle. Se usa la
    # de consulta como valor neutro porque el Auditor descarta estos eventos
    # en cuanto ve `region` en null, así que la elección no tiene efecto.
    accion = _ACCION_POR_OPERACION.get(sobre.operacion, AccionAuditoria.CONSULTA_POLIZA)
    try:
        if sobre.operacion == "consultar_poliza":
            return _consultar_poliza(repositorio, sobre.parametros)
        if sobre.operacion == "aprobar_poliza":
            return _aprobar_poliza(repositorio, sobre.parametros, sobre.actor.employee_id, ahora)
        return ResultadoOperacion(
            estado=EstadoRespuesta.ERROR,
            codigo=CodigoRespuesta.VALIDACION,
            accion=accion,
            error=f"operación desconocida: {sobre.operacion}",
        )
    except ErrorValidacionSobre as err:
        return ResultadoOperacion(
            estado=EstadoRespuesta.ERROR,
            codigo=CodigoRespuesta.VALIDACION,
            accion=accion,
            error=str(err),
        )
    except Exception:
        log.exception("operación fallida inesperadamente", extra={"operacion": sobre.operacion})
        return ResultadoOperacion(
            estado=EstadoRespuesta.ERROR,
            codigo=CodigoRespuesta.INTERNO,
            accion=accion,
            error="error interno",
        )


def _consultar_poliza(
    repositorio: Repositorio, parametros: Mapping[str, Any]
) -> ResultadoOperacion:
    datos = ParametrosPoliza.desde_dict(parametros)
    poliza = repositorio.poliza_por_id(datos.poliza_id)
    if poliza is None:
        return ResultadoOperacion(
            estado=EstadoRespuesta.ERROR,
            codigo=CodigoRespuesta.NO_ENCONTRADA,
            accion=AccionAuditoria.CONSULTA_POLIZA,
            error=f"póliza {datos.poliza_id} no encontrada",
            poliza_id=datos.poliza_id,
        )
    return ResultadoOperacion(
        estado=EstadoRespuesta.OK,
        codigo=CodigoRespuesta.OK,
        accion=AccionAuditoria.CONSULTA_POLIZA,
        resultado=poliza.a_dict(),
        poliza_id=poliza.poliza_id,
        region=poliza.region,
        cliente_id=poliza.cliente_id,
    )


def _aprobar_poliza(
    repositorio: Repositorio,
    parametros: Mapping[str, Any],
    actor_employee_id: str,
    ahora: datetime,
) -> ResultadoOperacion:
    datos = ParametrosPoliza.desde_dict(parametros)
    poliza = repositorio.aprobar_poliza(datos.poliza_id, actor_employee_id, ahora)
    if poliza is None:
        existente = repositorio.poliza_por_id(datos.poliza_id)
        if existente is None:
            return ResultadoOperacion(
                estado=EstadoRespuesta.ERROR,
                codigo=CodigoRespuesta.NO_ENCONTRADA,
                accion=AccionAuditoria.APROBACION_POLIZA,
                error=f"póliza {datos.poliza_id} no encontrada",
                poliza_id=datos.poliza_id,
            )
        return ResultadoOperacion(
            estado=EstadoRespuesta.ERROR,
            codigo=CodigoRespuesta.ESTADO_INVALIDO,
            accion=AccionAuditoria.APROBACION_POLIZA,
            error=f"póliza {datos.poliza_id} no está PENDIENTE",
            poliza_id=existente.poliza_id,
            region=existente.region,
            cliente_id=existente.cliente_id,
        )
    resultado_dict = poliza.a_dict()
    return ResultadoOperacion(
        estado=EstadoRespuesta.OK,
        codigo=CodigoRespuesta.OK,
        accion=AccionAuditoria.APROBACION_POLIZA,
        resultado={
            "poliza_id": poliza.poliza_id,
            "estado": resultado_dict["estado"],
            "aprobada_por": resultado_dict["aprobada_por"],
            "aprobada_en": resultado_dict["aprobada_en"],
        },
        poliza_id=poliza.poliza_id,
        region=poliza.region,
        cliente_id=poliza.cliente_id,
    )
