"""Persistencia en SQLite (biblioteca estándar, modo WAL).

Una conexión por operación: el worker es un solo hilo, pero abrir y cerrar
cuesta microsegundos con WAL y evita retener una conexión entre ciclos.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from auditor.contracts import HistorialEntrada, desde_iso_utc, iso_utc

ESQUEMA = """
CREATE TABLE IF NOT EXISTS historial (
    employee_id     TEXT NOT NULL,
    region          TEXT NOT NULL,
    conteo          INTEGER NOT NULL,
    primera_vez     TEXT NOT NULL,
    ultima_vez      TEXT NOT NULL,
    PRIMARY KEY (employee_id, region)
);
"""


def _fila_a_entrada(fila: sqlite3.Row) -> HistorialEntrada:
    return HistorialEntrada(
        employee_id=fila["employee_id"],
        region=fila["region"],
        conteo=int(fila["conteo"]),
        primera_vez=desde_iso_utc(fila["primera_vez"]),
        ultima_vez=desde_iso_utc(fila["ultima_vez"]),
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

    def contar_historial(self) -> int:
        with self._transaccion() as conexion:
            fila = conexion.execute("SELECT COUNT(*) AS n FROM historial").fetchone()
            return int(fila["n"])

    def insertar_historial(self, entradas: list[HistorialEntrada]) -> None:
        with self._transaccion() as conexion:
            conexion.executemany(
                "INSERT INTO historial (employee_id, region, conteo, primera_vez, ultima_vez)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        e.employee_id,
                        e.region,
                        e.conteo,
                        iso_utc(e.primera_vez),
                        iso_utc(e.ultima_vez),
                    )
                    for e in entradas
                ],
            )

    def entrada(self, employee_id: str, region: str) -> HistorialEntrada | None:
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT * FROM historial WHERE employee_id = ? AND region = ?",
                (employee_id, region),
            ).fetchone()
            return _fila_a_entrada(fila) if fila else None

    def tiene_region(self, employee_id: str, region: str) -> bool:
        return self.entrada(employee_id, region) is not None

    def incrementar(self, employee_id: str, region: str, ahora: datetime) -> None:
        """La región ya era habitual: la consulta cuenta a favor del patrón conocido."""
        with self._transaccion() as conexion:
            conexion.execute(
                "UPDATE historial SET conteo = conteo + 1, ultima_vez = ?"
                " WHERE employee_id = ? AND region = ?",
                (iso_utc(ahora), employee_id, region),
            )

    def incorporar(self, employee_id: str, region: str, ahora: datetime) -> None:
        """Una región nueva que Validación calificó de legítima pasa a ser habitual."""
        with self._transaccion() as conexion:
            conexion.execute(
                "INSERT INTO historial (employee_id, region, conteo, primera_vez, ultima_vez)"
                " VALUES (?, ?, 1, ?, ?)"
                " ON CONFLICT (employee_id, region) DO UPDATE SET"
                "   conteo = conteo + 1, ultima_vez = excluded.ultima_vez",
                (employee_id, region, iso_utc(ahora), iso_utc(ahora)),
            )
