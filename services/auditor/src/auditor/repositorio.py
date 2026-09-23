"""Persistencia del historial de regiones en SQLite (biblioteca estándar, WAL).

El Auditor es un solo hilo, pero se conserva el patrón de una conexión por
operación de los demás servicios: el coste es de microsegundos y así ninguna
conexión sobrevive a un fallo a mitad de ciclo.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from auditor.contracts import Habito, desde_iso_utc, iso_utc_ms

ESQUEMA = """
CREATE TABLE IF NOT EXISTS historial (
    employee_id  TEXT NOT NULL,
    region       TEXT NOT NULL,
    conteo       INTEGER NOT NULL,
    primera_vez  TEXT NOT NULL,
    ultima_vez   TEXT NOT NULL,
    PRIMARY KEY (employee_id, region)
);
"""


def _fila_a_habito(fila: sqlite3.Row) -> Habito:
    return Habito(
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

    def contar(self) -> int:
        with self._transaccion() as conexion:
            return int(conexion.execute("SELECT COUNT(*) AS n FROM historial").fetchone()["n"])

    def insertar(self, habitos: list[Habito]) -> None:
        with self._transaccion() as conexion:
            conexion.executemany(
                "INSERT INTO historial (employee_id, region, conteo, primera_vez, ultima_vez)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        h.employee_id,
                        h.region,
                        h.conteo,
                        iso_utc_ms(h.primera_vez),
                        iso_utc_ms(h.ultima_vez),
                    )
                    for h in habitos
                ],
            )

    def habitos(self, employee_id: str) -> list[Habito]:
        with self._transaccion() as conexion:
            filas = conexion.execute(
                "SELECT * FROM historial WHERE employee_id = ? ORDER BY region", (employee_id,)
            ).fetchall()
            return [_fila_a_habito(fila) for fila in filas]

    def registrar_observacion(self, employee_id: str, region: str, ahora: datetime) -> bool:
        """Suma una consulta a una región habitual. `False` si la región no es
        habitual para el empleado (entonces no toca nada)."""
        with self._transaccion() as conexion:
            cursor = conexion.execute(
                "UPDATE historial SET conteo = conteo + 1, ultima_vez = ?"
                " WHERE employee_id = ? AND region = ?",
                (iso_utc_ms(ahora), employee_id, region),
            )
            return cursor.rowcount == 1

    def incorporar(self, employee_id: str, region: str, ahora: datetime) -> None:
        """Vuelve habitual una región (decisión `ALERTAR`). Idempotente: si el
        evento se reprocesa tras un corte, cuenta la observación en vez de fallar."""
        instante = iso_utc_ms(ahora)
        with self._transaccion() as conexion:
            conexion.execute(
                "INSERT INTO historial (employee_id, region, conteo, primera_vez, ultima_vez)"
                " VALUES (?, ?, 1, ?, ?)"
                " ON CONFLICT (employee_id, region)"
                " DO UPDATE SET conteo = conteo + 1, ultima_vez = excluded.ultima_vez",
                (employee_id, region, instante, instante),
            )
