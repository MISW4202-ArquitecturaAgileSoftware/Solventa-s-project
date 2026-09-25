"""Escenarios secuenciales deterministas del experimento (PLAN-IMPLEMENTACION.md
§6, F9): cada uno es un único actor, de principio a fin, y devuelve un
dataclass de resultado con la evidencia que `metricas.py` necesita.

La carga concurrente (AAS-H710 exige demostrar el hallazgo también bajo
concurrencia real) vive aparte, en `locustfile.py`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from cliente import ClienteExperimento, Respuesta
from entorno import PASSWORD, Empleado

_LIMITE_REINTENTO_S = 10.0
_INTERVALO_REINTENTO_S = 0.1


def _reintentar_hasta(
    solicitar: Callable[[], Respuesta],
    estado_esperado: int,
    tipo_esperado: str,
    limite_s: float = _LIMITE_REINTENTO_S,
    intervalo_s: float = _INTERVALO_REINTENTO_S,
) -> tuple[Respuesta, float]:
    """Reintenta `solicitar` hasta obtener `(estado_esperado, tipo_esperado)` o
    agotar `limite_s`. Devuelve la última respuesta y el instante en que se
    obtuvo (`time.perf_counter()`), para medir la latencia de revocación."""
    inicio = time.perf_counter()
    respuesta = solicitar()
    while not (respuesta.estado == estado_esperado and respuesta.tipo_error == tipo_esperado):
        if time.perf_counter() - inicio >= limite_s:
            break
        time.sleep(intervalo_s)
        respuesta = solicitar()
    return respuesta, time.perf_counter()


@dataclass(frozen=True, slots=True)
class ResultadoAtacanteAsr23:
    employee_id: str
    poliza_id: str
    session_id: str
    estado_aprobacion_1: int
    estado_otp: int
    tipo_error_otp: str | None
    estado_aprobacion_2: int
    tipo_error_aprobacion_2: str | None
    latencia_revocacion_ms: float


def atacante_asr23(
    cliente: ClienteExperimento, empleado: Empleado, poliza_id: str
) -> ResultadoAtacanteAsr23:
    """Altera su propio rol, inicia sesión con el token ya elevado, pide la
    aprobación (§202 OTP_REQUERIDO), falla el OTP a propósito y reintenta la
    segunda aprobación hasta que Reacción revoque la sesión."""
    cliente.alterar_rol(empleado.employee_id, "supervisor")
    login = cliente.login(empleado.usuario, PASSWORD)
    token = str(login.cuerpo["token"])
    session_id = str(login.cuerpo["session_id"])

    primera = cliente.aprobar_poliza(token, poliza_id)
    otp = cliente.resolver_otp(token, "000000")
    t_403 = time.perf_counter()
    segunda, t_401 = _reintentar_hasta(
        lambda: cliente.aprobar_poliza(token, poliza_id), 401, "sesion-revocada"
    )

    return ResultadoAtacanteAsr23(
        employee_id=empleado.employee_id,
        poliza_id=poliza_id,
        session_id=session_id,
        estado_aprobacion_1=primera.estado,
        estado_otp=otp.estado,
        tipo_error_otp=otp.tipo_error,
        estado_aprobacion_2=segunda.estado,
        tipo_error_aprobacion_2=segunda.tipo_error,
        latencia_revocacion_ms=(t_401 - t_403) * 1000,
    )


@dataclass(frozen=True, slots=True)
class ResultadoLegitimoAsr23:
    employee_id: str
    poliza_id: str
    session_id: str
    estado_aprobacion_1: int
    estado_otp: int
    estado_operacion_resultado: str | None
    estado_consulta_2: int


def legitimo_asr23(
    cliente: ClienteExperimento, empleado: Empleado, poliza_id: str
) -> ResultadoLegitimoAsr23:
    """El mismo camino que el atacante, pero leyendo el código real del canal
    OTP simulado en vez de inventarlo."""
    cliente.alterar_rol(empleado.employee_id, "supervisor")
    login = cliente.login(empleado.usuario, PASSWORD)
    token = str(login.cuerpo["token"])
    session_id = str(login.cuerpo["session_id"])

    primera = cliente.aprobar_poliza(token, poliza_id)
    otp_leido = cliente.leer_otp(session_id)
    codigo = str(otp_leido.cuerpo["codigo"])
    resuelto = cliente.resolver_otp(token, codigo)

    operacion = resuelto.cuerpo.get("operacion")
    resultado_operacion = operacion.get("resultado") if isinstance(operacion, dict) else None
    estado_operacion = (
        resultado_operacion.get("estado") if isinstance(resultado_operacion, dict) else None
    )
    segunda = cliente.consultar_poliza(token, poliza_id)

    return ResultadoLegitimoAsr23(
        employee_id=empleado.employee_id,
        poliza_id=poliza_id,
        session_id=session_id,
        estado_aprobacion_1=primera.estado,
        estado_otp=resuelto.estado,
        estado_operacion_resultado=estado_operacion,
        estado_consulta_2=segunda.estado,
    )


@dataclass(frozen=True, slots=True)
class ResultadoAtacanteAsr31Secuencial:
    employee_id: str
    poliza_id: str
    session_id: str
    estado_consulta_1: int
    estado_consulta_2: int
    tipo_error_consulta_2: str | None


def atacante_asr31_secuencial(
    cliente: ClienteExperimento, empleado: Empleado, poliza_sur: str, periodo_s: int
) -> ResultadoAtacanteAsr31Secuencial:
    """Un asesor de `norte` que consulta una póliza de `sur`, fuera de su
    alcance. La primera consulta se resuelve antes de que el Auditor la vea;
    la segunda, tras esperar un ciclo completo de más, ya la encuentra
    revocada."""
    login = cliente.login(empleado.usuario, PASSWORD)
    token = str(login.cuerpo["token"])
    session_id = str(login.cuerpo["session_id"])

    primera = cliente.consultar_poliza(token, poliza_sur)
    time.sleep(periodo_s + 3)
    segunda, _ = _reintentar_hasta(
        lambda: cliente.consultar_poliza(token, poliza_sur), 401, "sesion-revocada"
    )

    return ResultadoAtacanteAsr31Secuencial(
        employee_id=empleado.employee_id,
        poliza_id=poliza_sur,
        session_id=session_id,
        estado_consulta_1=primera.estado,
        estado_consulta_2=segunda.estado,
        tipo_error_consulta_2=segunda.tipo_error,
    )


@dataclass(frozen=True, slots=True)
class ResultadoLegitimoInusualAsr31:
    employee_id: str
    poliza_id: str
    session_id: str
    estado_consulta_1: int
    estado_consulta_2: int


def legitimo_inusual_asr31(
    cliente: ClienteExperimento, empleado: Empleado, poliza_centro: str, periodo_s: int
) -> ResultadoLegitimoInusualAsr31:
    """Un asesor con alcance `[norte, centro]` que consulta `centro`: fuera de
    su historial pero dentro de su alcance autorizado. El Auditor debe
    alertar (`CONSULTA_INUSUAL`) sin revocar."""
    login = cliente.login(empleado.usuario, PASSWORD)
    token = str(login.cuerpo["token"])
    session_id = str(login.cuerpo["session_id"])

    primera = cliente.consultar_poliza(token, poliza_centro)
    time.sleep(periodo_s + 3)
    segunda = cliente.consultar_poliza(token, poliza_centro)

    return ResultadoLegitimoInusualAsr31(
        employee_id=empleado.employee_id,
        poliza_id=poliza_centro,
        session_id=session_id,
        estado_consulta_1=primera.estado,
        estado_consulta_2=segunda.estado,
    )


@dataclass(frozen=True, slots=True)
class ObservacionRafaga:
    t_s: float
    estado: int
    tipo_error: str | None


@dataclass(frozen=True, slots=True)
class ResultadoAtacanteAsr31Rafaga:
    employee_id: str
    session_id: str
    observaciones: tuple[ObservacionRafaga, ...]
    consultas_servidas_antes_del_401: int
    ventana_exposicion_ms: float | None
    total: int


def atacante_asr31_rafaga(
    cliente: ClienteExperimento,
    empleado: Empleado,
    polizas_sur: Sequence[str],
    duracion_s: float,
    ritmo_por_s: float,
) -> ResultadoAtacanteAsr31Rafaga:
    """Un único atacante disparando consultas de `sur` a ritmo constante
    durante `duracion_s`: la versión de un solo actor de la ventana de
    exposición que `locustfile.py` mide bajo concurrencia real."""
    login = cliente.login(empleado.usuario, PASSWORD)
    token = str(login.cuerpo["token"])
    session_id = str(login.cuerpo["session_id"])

    intervalo_s = 1.0 / ritmo_por_s
    inicio = time.perf_counter()
    observaciones: list[ObservacionRafaga] = []
    primer_401_s: float | None = None
    indice = 0
    while time.perf_counter() - inicio < duracion_s:
        poliza_id = polizas_sur[indice % len(polizas_sur)]
        respuesta = cliente.consultar_poliza(token, poliza_id)
        transcurrido = time.perf_counter() - inicio
        observaciones.append(
            ObservacionRafaga(
                t_s=transcurrido, estado=respuesta.estado, tipo_error=respuesta.tipo_error
            )
        )
        if respuesta.estado == 401 and primer_401_s is None:
            primer_401_s = transcurrido
        indice += 1
        time.sleep(intervalo_s)

    servidas = sum(
        1
        for observacion in observaciones
        if observacion.estado == 200 and (primer_401_s is None or observacion.t_s < primer_401_s)
    )
    return ResultadoAtacanteAsr31Rafaga(
        employee_id=empleado.employee_id,
        session_id=session_id,
        observaciones=tuple(observaciones),
        consultas_servidas_antes_del_401=servidas,
        ventana_exposicion_ms=primer_401_s * 1000 if primer_401_s is not None else None,
        total=len(observaciones),
    )
