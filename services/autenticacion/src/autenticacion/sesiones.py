"""Casos de uso de Autenticación: iniciar, verificar, revocar, bloquear, alterar rol."""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from autenticacion import contrasenas, tokens
from autenticacion.config import Config
from autenticacion.contracts import (
    MotivoInvalidez,
    Rol,
    Sesion,
    SesionEmitida,
    Verificacion,
    ahora_utc,
)
from autenticacion.errors import ErrorCredenciales, ErrorEmpleadoBloqueado, ErrorNoEncontrado
from autenticacion.repositorio import Repositorio

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResultadoRevocacion:
    session_id: str
    revocada_en: datetime
    ya_estaba_revocada: bool


@dataclass(frozen=True, slots=True)
class ResultadoBloqueo:
    employee_id: str
    bloqueado_en: datetime
    ya_estaba_bloqueado: bool
    sesiones_afectadas: int


@dataclass(frozen=True, slots=True)
class CambioRol:
    employee_id: str
    rol_anterior: Rol
    rol: Rol


class ServicioSesiones:
    def __init__(self, repositorio: Repositorio, config: Config) -> None:
        self.repositorio = repositorio
        self.config = config

    def iniciar(self, usuario: str, password: str) -> SesionEmitida:
        empleado = self.repositorio.empleado_por_usuario(usuario)
        if empleado is None or not contrasenas.verificar(password, empleado.hash_password):
            log.warning("login rechazado", extra={"usuario": usuario})
            raise ErrorCredenciales("usuario o contraseña incorrectos")
        if empleado.bloqueado:
            log.warning("login de empleado bloqueado", extra={"employee_id": empleado.employee_id})
            raise ErrorEmpleadoBloqueado(f"{empleado.employee_id} está bloqueado")

        ahora = ahora_utc()
        sesion = Sesion(
            session_id=str(uuid.uuid7()),
            employee_id=empleado.employee_id,
            rol=empleado.rol,
            emitida_en=ahora,
            expira_en=ahora + timedelta(seconds=self.config.jwt_ttl_s),
        )
        self.repositorio.crear_sesion(sesion)
        token = tokens.emitir(
            self.config.jwt_secret,
            sesion.employee_id,
            sesion.session_id,
            sesion.rol,
            sesion.emitida_en,
            sesion.expira_en,
        )
        log.info(
            "sesión emitida",
            extra={
                "employee_id": sesion.employee_id,
                "session_id": sesion.session_id,
                "rol": sesion.rol.value,
            },
        )
        return SesionEmitida(
            session_id=sesion.session_id,
            employee_id=sesion.employee_id,
            rol=sesion.rol,
            token=token,
            expira_en=sesion.expira_en,
        )

    def verificar(self, token: str) -> Verificacion:
        """Orden fijado en PLAN-IMPLEMENTACION.md §5.6."""
        try:
            claims = tokens.decodificar(self.config.jwt_secret, token)
        except tokens.ErrorTokenExpirado as err:
            return Verificacion(False, MotivoInvalidez.EXPIRADA, session_id=err.session_id)
        except tokens.ErrorTokenInvalido:
            return Verificacion(False, MotivoInvalidez.INVALIDA)

        sesion = self.repositorio.sesion(claims.session_id)
        if sesion is None:
            # Token firmado por una vida anterior del servicio (base reiniciada).
            return Verificacion(False, MotivoInvalidez.INVALIDA)
        if sesion.revocada:
            return Verificacion(
                False,
                MotivoInvalidez.REVOCADA,
                employee_id=sesion.employee_id,
                session_id=sesion.session_id,
            )
        empleado = self.repositorio.empleado_por_id(sesion.employee_id)
        if empleado is None or empleado.bloqueado:
            return Verificacion(
                False,
                MotivoInvalidez.BLOQUEADO,
                employee_id=sesion.employee_id,
                session_id=sesion.session_id,
            )
        return Verificacion(
            True,
            employee_id=sesion.employee_id,
            session_id=sesion.session_id,
            rol=sesion.rol,
        )

    def revocar(self, session_id: str, motivo: str, correlation_id: str) -> ResultadoRevocacion:
        resultado = self.repositorio.revocar_sesion(session_id, motivo, correlation_id, ahora_utc())
        if resultado is None:
            raise ErrorNoEncontrado(f"sesión {session_id} no existe")
        revocada_en, ya_estaba = resultado
        log.info(
            "sesión revocada",
            extra={"session_id": session_id, "motivo": motivo, "ya_estaba_revocada": ya_estaba},
        )
        return ResultadoRevocacion(session_id, revocada_en, ya_estaba)

    def bloquear(self, employee_id: str, motivo: str) -> ResultadoBloqueo:
        resultado = self.repositorio.bloquear_empleado(employee_id, motivo, ahora_utc())
        if resultado is None:
            raise ErrorNoEncontrado(f"empleado {employee_id} no existe")
        bloqueado_en, ya_estaba, vivas = resultado
        log.info(
            "empleado bloqueado",
            extra={
                "employee_id": employee_id,
                "motivo": motivo,
                "ya_estaba_bloqueado": ya_estaba,
                "sesiones_afectadas": vivas,
            },
        )
        return ResultadoBloqueo(employee_id, bloqueado_en, ya_estaba, vivas)

    def alterar_rol(self, employee_id: str, rol: Rol) -> CambioRol:
        """La alteración del atacante. Solo existe en modo experimento."""
        anterior = self.repositorio.cambiar_rol(employee_id, rol)
        if anterior is None:
            raise ErrorNoEncontrado(f"empleado {employee_id} no existe")
        log.warning(
            "rol alterado (experimento)",
            extra={"employee_id": employee_id, "rol_anterior": anterior.value, "rol": rol.value},
        )
        return CambioRol(employee_id, anterior, rol)
