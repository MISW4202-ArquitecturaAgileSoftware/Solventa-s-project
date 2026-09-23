"""Persistencia en SQLite (biblioteca estándar, modo WAL).

Una conexión por operación: gunicorn atiende con hilos y `sqlite3` no permite
compartir conexiones entre ellos. Abrir y cerrar cuesta microsegundos con WAL.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from validacion.contracts import (
    AccionSeguridad,
    Alerta,
    Autorizacion,
    MotivoSeguridad,
    Operacion,
    OtpPendiente,
    Rol,
    SobreOperacion,
    desde_iso_utc,
    iso_utc,
    iso_utc_ms,
)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS permisos_rol (
    rol       TEXT NOT NULL,
    operacion TEXT NOT NULL,
    PRIMARY KEY (rol, operacion)
);
CREATE TABLE IF NOT EXISTS autorizaciones (
    employee_id           TEXT PRIMARY KEY,
    ultimo_rol_observado   TEXT NOT NULL,
    alcance_autorizado     TEXT NOT NULL,
    canal_otp              TEXT NOT NULL,
    actualizado_en         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS otp_pendientes (
    session_id      TEXT PRIMARY KEY,
    codigo          TEXT NOT NULL,
    correlation_id  TEXT NOT NULL,
    sobre           TEXT NOT NULL,
    creado_en       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alertas (
    evento_id       TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    employee_id     TEXT NOT NULL,
    motivo          TEXT NOT NULL,
    accion          TEXT NOT NULL,
    correlation_id  TEXT NOT NULL,
    detalle         TEXT NOT NULL,
    recibida_en     TEXT NOT NULL,
    revocada_en     TEXT,
    bloqueado_en    TEXT,
    UNIQUE (session_id, motivo)
);
"""


def _opcional(valor: str | None) -> datetime | None:
    return desde_iso_utc(valor) if valor else None


def _fila_a_alerta(fila: sqlite3.Row) -> Alerta:
    return Alerta(
        evento_id=fila["evento_id"],
        session_id=fila["session_id"],
        employee_id=fila["employee_id"],
        motivo=MotivoSeguridad(fila["motivo"]),
        accion=AccionSeguridad(fila["accion"]),
        correlation_id=fila["correlation_id"],
        detalle=json.loads(fila["detalle"]),
        recibida_en=desde_iso_utc(fila["recibida_en"]),
        revocada_en=_opcional(fila["revocada_en"]),
        bloqueado_en=_opcional(fila["bloqueado_en"]),
    )


def _fila_a_autorizacion(fila: sqlite3.Row) -> Autorizacion:
    return Autorizacion(
        employee_id=fila["employee_id"],
        ultimo_rol_observado=Rol(fila["ultimo_rol_observado"]),
        alcance_autorizado=list(json.loads(fila["alcance_autorizado"])),
        canal_otp=fila["canal_otp"],
        actualizado_en=desde_iso_utc(fila["actualizado_en"]),
    )


def _fila_a_pendiente(fila: sqlite3.Row) -> OtpPendiente:
    return OtpPendiente(
        session_id=fila["session_id"],
        codigo=fila["codigo"],
        correlation_id=fila["correlation_id"],
        sobre=SobreOperacion.desde_dict(json.loads(fila["sobre"])),
        creado_en=desde_iso_utc(fila["creado_en"]),
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

    # --- permisos_rol ----------------------------------------------------------

    def contar_permisos(self) -> int:
        with self._transaccion() as conexion:
            fila = conexion.execute("SELECT COUNT(*) AS n FROM permisos_rol").fetchone()
            return int(fila["n"])

    def insertar_permisos(self, permisos: list[tuple[Rol, Operacion]]) -> None:
        with self._transaccion() as conexion:
            conexion.executemany(
                "INSERT INTO permisos_rol (rol, operacion) VALUES (?, ?)",
                [(rol.value, operacion.value) for rol, operacion in permisos],
            )

    def operacion_permitida(self, rol: Rol, operacion: Operacion) -> bool:
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT 1 FROM permisos_rol WHERE rol = ? AND operacion = ?",
                (rol.value, operacion.value),
            ).fetchone()
            return fila is not None

    # --- autorizaciones ----------------------------------------------------------

    def contar_autorizaciones(self) -> int:
        with self._transaccion() as conexion:
            fila = conexion.execute("SELECT COUNT(*) AS n FROM autorizaciones").fetchone()
            return int(fila["n"])

    def insertar_autorizaciones(self, autorizaciones: list[Autorizacion]) -> None:
        with self._transaccion() as conexion:
            conexion.executemany(
                "INSERT INTO autorizaciones"
                " (employee_id, ultimo_rol_observado, alcance_autorizado, canal_otp,"
                "  actualizado_en)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        a.employee_id,
                        a.ultimo_rol_observado.value,
                        json.dumps(a.alcance_autorizado, ensure_ascii=False),
                        a.canal_otp,
                        iso_utc(a.actualizado_en),
                    )
                    for a in autorizaciones
                ],
            )

    def autorizacion(self, employee_id: str) -> Autorizacion | None:
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT * FROM autorizaciones WHERE employee_id = ?", (employee_id,)
            ).fetchone()
            return _fila_a_autorizacion(fila) if fila else None

    def actualizar_rol_observado(self, employee_id: str, rol: Rol, ahora: datetime) -> None:
        with self._transaccion() as conexion:
            conexion.execute(
                "UPDATE autorizaciones SET ultimo_rol_observado = ?, actualizado_en = ?"
                " WHERE employee_id = ?",
                (rol.value, iso_utc(ahora), employee_id),
            )

    # --- otp_pendientes ----------------------------------------------------------

    def otp_pendiente(self, session_id: str) -> OtpPendiente | None:
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT * FROM otp_pendientes WHERE session_id = ?", (session_id,)
            ).fetchone()
            return _fila_a_pendiente(fila) if fila else None

    def guardar_otp_pendiente(self, pendiente: OtpPendiente) -> None:
        with self._transaccion() as conexion:
            conexion.execute(
                "INSERT INTO otp_pendientes (session_id, codigo, correlation_id, sobre, creado_en)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    pendiente.session_id,
                    pendiente.codigo,
                    pendiente.correlation_id,
                    json.dumps(pendiente.sobre.a_dict(), ensure_ascii=False),
                    iso_utc(pendiente.creado_en),
                ),
            )

    def borrar_otp_pendiente(self, session_id: str) -> None:
        with self._transaccion() as conexion:
            conexion.execute("DELETE FROM otp_pendientes WHERE session_id = ?", (session_id,))

    # --- alertas (Reacción, §5.5) ---------------------------------------------

    def alerta_por_clave(self, session_id: str, motivo: MotivoSeguridad) -> Alerta | None:
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT * FROM alertas WHERE session_id = ? AND motivo = ?",
                (session_id, motivo.value),
            ).fetchone()
            return _fila_a_alerta(fila) if fila else None

    def insertar_alerta(self, alerta: Alerta) -> None:
        with self._transaccion() as conexion:
            conexion.execute(
                "INSERT INTO alertas (evento_id, session_id, employee_id, motivo, accion,"
                " correlation_id, detalle, recibida_en, revocada_en, bloqueado_en)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    alerta.evento_id,
                    alerta.session_id,
                    alerta.employee_id,
                    alerta.motivo.value,
                    alerta.accion.value,
                    alerta.correlation_id,
                    json.dumps(alerta.detalle, ensure_ascii=False),
                    iso_utc_ms(alerta.recibida_en),
                    iso_utc_ms(alerta.revocada_en) if alerta.revocada_en is not None else None,
                    iso_utc_ms(alerta.bloqueado_en) if alerta.bloqueado_en is not None else None,
                ),
            )

    def marcar_alerta_contenida(
        self, evento_id: str, revocada_en: datetime, bloqueado_en: datetime
    ) -> None:
        with self._transaccion() as conexion:
            conexion.execute(
                "UPDATE alertas SET revocada_en = ?, bloqueado_en = ? WHERE evento_id = ?",
                (iso_utc_ms(revocada_en), iso_utc_ms(bloqueado_en), evento_id),
            )

    def listar_alertas(self) -> list[Alerta]:
        with self._transaccion() as conexion:
            filas = conexion.execute("SELECT * FROM alertas ORDER BY recibida_en").fetchall()
            return [_fila_a_alerta(fila) for fila in filas]
