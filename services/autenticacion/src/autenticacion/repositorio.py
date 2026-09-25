"""Persistencia en SQLite (biblioteca estándar, modo WAL).

Una conexión por operación: gunicorn atiende con hilos y `sqlite3` no permite
compartir conexiones entre ellos. Abrir y cerrar cuesta microsegundos con WAL.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
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
    session_id                  TEXT PRIMARY KEY,
    employee_id                 TEXT NOT NULL REFERENCES empleados(employee_id),
    rol                         TEXT NOT NULL,
    emitida_en                  TEXT NOT NULL,
    expira_en                   TEXT NOT NULL,
    revocada_en                 TEXT,
    motivo_revocacion           TEXT,
    correlation_id_revocacion   TEXT
);
CREATE INDEX IF NOT EXISTS sesiones_por_empleado ON sesiones(employee_id);
"""


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
    )


class Repositorio:
    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta

    @contextmanager
    def _transaccion(self) -> Iterator[sqlite3.Connection]:
        conexion = sqlite3.connect(self.ruta, timeout=5)
        conexion.row_factory = sqlite3.Row
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

    # --- empleados -----------------------------------------------------------

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

    def empleado_por_usuario(self, usuario: str) -> Empleado | None:
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT * FROM empleados WHERE usuario = ?", (usuario,)
            ).fetchone()
            return _fila_a_empleado(fila) if fila else None

    def empleado_por_id(self, employee_id: str) -> Empleado | None:
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT * FROM empleados WHERE employee_id = ?", (employee_id,)
            ).fetchone()
            return _fila_a_empleado(fila) if fila else None

    def bloquear_empleado(
        self, employee_id: str, motivo: str, ahora: datetime
    ) -> tuple[datetime, bool, int] | None:
        """Devuelve (bloqueado_en, ya_estaba_bloqueado, sesiones_vivas) o None."""
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT bloqueado_en FROM empleados WHERE employee_id = ?", (employee_id,)
            ).fetchone()
            if fila is None:
                return None
            vivas = conexion.execute(
                "SELECT COUNT(*) AS n FROM sesiones"
                " WHERE employee_id = ? AND revocada_en IS NULL AND expira_en > ?",
                (employee_id, iso_utc(ahora)),
            ).fetchone()
            if fila["bloqueado_en"]:
                return desde_iso_utc(fila["bloqueado_en"]), True, int(vivas["n"])
            conexion.execute(
                "UPDATE empleados SET bloqueado_en = ?, motivo_bloqueo = ? WHERE employee_id = ?",
                (iso_utc(ahora), motivo, employee_id),
            )
            return ahora, False, int(vivas["n"])

    def cambiar_rol(self, employee_id: str, rol: Rol) -> Rol | None:
        """Cambia el rol y devuelve el anterior, o None si el empleado no existe."""
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

    # --- sesiones ------------------------------------------------------------

    def crear_sesion(self, sesion: Sesion) -> None:
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

    def revocar_sesion(
        self, session_id: str, motivo: str, correlation_id: str, ahora: datetime
    ) -> tuple[datetime, bool] | None:
        """Devuelve (revocada_en, ya_estaba_revocada) o None si no existe."""
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT revocada_en FROM sesiones WHERE session_id = ?", (session_id,)
            ).fetchone()
            if fila is None:
                return None
            if fila["revocada_en"]:
                return desde_iso_utc(fila["revocada_en"]), True
            conexion.execute(
                "UPDATE sesiones SET revocada_en = ?, motivo_revocacion = ?,"
                " correlation_id_revocacion = ? WHERE session_id = ?",
                (iso_utc(ahora), motivo, correlation_id, session_id),
            )
            return ahora, False
