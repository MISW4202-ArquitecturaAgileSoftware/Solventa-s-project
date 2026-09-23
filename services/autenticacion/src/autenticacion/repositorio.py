"""Persistencia en SQLite (biblioteca estándar, modo WAL).

Una conexión por operación: gunicorn atiende con hilos y `sqlite3` no permite
compartir conexiones entre ellos. Abrir y cerrar cuesta microsegundos con WAL.

Revocación y bloqueo son idempotentes (§3.3) y lo son de forma atómica: el
`UPDATE … WHERE … IS NULL` solo lo gana una petición aunque Reacción reintente
en paralelo, y la que pierde lee el instante que fijó la ganadora.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from autenticacion.contracts import Empleado, Rol, Sesion, desde_iso_utc, iso_utc

ESQUEMA = """
CREATE TABLE IF NOT EXISTS empleados (
    employee_id     TEXT PRIMARY KEY,
    usuario         TEXT NOT NULL UNIQUE,
    hash_password   TEXT NOT NULL,
    rol             TEXT NOT NULL,
    bloqueado_en    TEXT,
    motivo_bloqueo  TEXT
);
CREATE TABLE IF NOT EXISTS sesiones (
    session_id                 TEXT PRIMARY KEY,
    employee_id                TEXT NOT NULL REFERENCES empleados (employee_id),
    rol                        TEXT NOT NULL,
    emitida_en                 TEXT NOT NULL,
    expira_en                  TEXT NOT NULL,
    revocada_en                TEXT,
    motivo_revocacion          TEXT,
    correlation_id_revocacion  TEXT
);
CREATE INDEX IF NOT EXISTS sesiones_por_empleado ON sesiones (employee_id);
"""


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
    #: Sesiones no revocadas ni expiradas que el bloqueo acaba de invalidar.
    #: Si el empleado ya estaba bloqueado es 0: este bloqueo no afectó a nadie.
    sesiones_afectadas: int


def _opcional(valor: str | None) -> datetime | None:
    return desde_iso_utc(valor) if valor else None


def _fila_a_empleado(fila: sqlite3.Row) -> Empleado:
    return Empleado(
        employee_id=fila["employee_id"],
        usuario=fila["usuario"],
        hash_password=fila["hash_password"],
        rol=Rol(fila["rol"]),
        bloqueado_en=_opcional(fila["bloqueado_en"]),
        motivo_bloqueo=fila["motivo_bloqueo"],
    )


def _fila_a_sesion(fila: sqlite3.Row) -> Sesion:
    return Sesion(
        session_id=fila["session_id"],
        employee_id=fila["employee_id"],
        rol=Rol(fila["rol"]),
        emitida_en=desde_iso_utc(fila["emitida_en"]),
        expira_en=desde_iso_utc(fila["expira_en"]),
        revocada_en=_opcional(fila["revocada_en"]),
        motivo_revocacion=fila["motivo_revocacion"],
        correlation_id_revocacion=fila["correlation_id_revocacion"],
    )


class Repositorio:
    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta

    @contextmanager
    def _transaccion(self) -> Iterator[sqlite3.Connection]:
        conexion = sqlite3.connect(self.ruta, timeout=5)
        conexion.row_factory = sqlite3.Row
        conexion.execute("PRAGMA foreign_keys = ON")
        try:
            with conexion:
                yield conexion
        finally:
            conexion.close()

    def inicializar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self._transaccion() as conexion:
            conexion.execute("PRAGMA journal_mode=WAL")
            conexion.executescript(ESQUEMA)

    # --- empleados -------------------------------------------------------------

    def contar_empleados(self) -> int:
        with self._transaccion() as conexion:
            fila = conexion.execute("SELECT COUNT(*) AS n FROM empleados").fetchone()
            return int(fila["n"])

    def insertar_empleados(self, empleados: list[Empleado]) -> None:
        with self._transaccion() as conexion:
            conexion.executemany(
                "INSERT INTO empleados (employee_id, usuario, hash_password, rol)"
                " VALUES (?, ?, ?, ?)",
                [(e.employee_id, e.usuario, e.hash_password, e.rol.value) for e in empleados],
            )

    def empleado(self, employee_id: str) -> Empleado | None:
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT * FROM empleados WHERE employee_id = ?", (employee_id,)
            ).fetchone()
            return _fila_a_empleado(fila) if fila else None

    def empleado_por_usuario(self, usuario: str) -> Empleado | None:
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT * FROM empleados WHERE usuario = ?", (usuario,)
            ).fetchone()
            return _fila_a_empleado(fila) if fila else None

    def cambiar_rol(self, employee_id: str, rol: Rol) -> Rol | None:
        """Devuelve el rol anterior, o `None` si el empleado no existe. Solo toca
        `empleados.rol`: las sesiones vivas conservan el rol con el que nacieron."""
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT rol FROM empleados WHERE employee_id = ?", (employee_id,)
            ).fetchone()
            if fila is None:
                return None
            conexion.execute(
                "UPDATE empleados SET rol = ? WHERE employee_id = ?", (rol.value, employee_id)
            )
            return Rol(fila["rol"])

    def bloquear(self, employee_id: str, motivo: str, ahora: datetime) -> ResultadoBloqueo | None:
        """`None` si el empleado no existe."""
        instante = iso_utc(ahora)
        with self._transaccion() as conexion:
            cursor = conexion.execute(
                "UPDATE empleados SET bloqueado_en = ?, motivo_bloqueo = ?"
                " WHERE employee_id = ? AND bloqueado_en IS NULL",
                (instante, motivo, employee_id),
            )
            if cursor.rowcount == 1:
                vivas = conexion.execute(
                    "SELECT COUNT(*) AS n FROM sesiones"
                    " WHERE employee_id = ? AND revocada_en IS NULL AND expira_en > ?",
                    (employee_id, instante),
                ).fetchone()
                return ResultadoBloqueo(
                    employee_id=employee_id,
                    bloqueado_en=desde_iso_utc(instante),
                    ya_estaba_bloqueado=False,
                    sesiones_afectadas=int(vivas["n"]),
                )
            fila = conexion.execute(
                "SELECT bloqueado_en FROM empleados WHERE employee_id = ?", (employee_id,)
            ).fetchone()
            if fila is None:
                return None
            return ResultadoBloqueo(
                employee_id=employee_id,
                bloqueado_en=desde_iso_utc(fila["bloqueado_en"]),
                ya_estaba_bloqueado=True,
                sesiones_afectadas=0,
            )

    # --- sesiones --------------------------------------------------------------

    def insertar_sesion(self, sesion: Sesion) -> None:
        with self._transaccion() as conexion:
            conexion.execute(
                "INSERT INTO sesiones (session_id, employee_id, rol, emitida_en, expira_en)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    sesion.session_id,
                    sesion.employee_id,
                    sesion.rol.value,
                    iso_utc(sesion.emitida_en),
                    iso_utc(sesion.expira_en),
                ),
            )

    def sesion(self, session_id: str) -> Sesion | None:
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT * FROM sesiones WHERE session_id = ?", (session_id,)
            ).fetchone()
            return _fila_a_sesion(fila) if fila else None

    def revocar(
        self, session_id: str, motivo: str, correlation_id: str, ahora: datetime
    ) -> ResultadoRevocacion | None:
        """`None` si la sesión no existe."""
        instante = iso_utc(ahora)
        with self._transaccion() as conexion:
            cursor = conexion.execute(
                "UPDATE sesiones"
                " SET revocada_en = ?, motivo_revocacion = ?, correlation_id_revocacion = ?"
                " WHERE session_id = ? AND revocada_en IS NULL",
                (instante, motivo, correlation_id, session_id),
            )
            if cursor.rowcount == 1:
                return ResultadoRevocacion(
                    session_id=session_id,
                    revocada_en=desde_iso_utc(instante),
                    ya_estaba_revocada=False,
                )
            fila = conexion.execute(
                "SELECT revocada_en FROM sesiones WHERE session_id = ?", (session_id,)
            ).fetchone()
            if fila is None:
                return None
            return ResultadoRevocacion(
                session_id=session_id,
                revocada_en=desde_iso_utc(fila["revocada_en"]),
                ya_estaba_revocada=True,
            )
