"""Persistencia en SQLite (biblioteca estándar, modo WAL).

Una conexión por operación: el worker procesa mensajes uno a uno en un solo
hilo, pero abrir y cerrar por operación evita conexiones colgadas si el
proceso se recicla y cuesta microsegundos con WAL.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from gestion_polizas.contracts import EstadoPoliza, Poliza, desde_iso_utc, iso_utc

ESQUEMA = """
CREATE TABLE IF NOT EXISTS polizas (
    poliza_id       TEXT PRIMARY KEY,
    cliente_id      TEXT NOT NULL,
    region          TEXT NOT NULL,
    producto        TEXT NOT NULL,
    suma_asegurada  TEXT NOT NULL,
    prima_mensual   TEXT NOT NULL,
    estado          TEXT NOT NULL,
    aprobada_por    TEXT,
    aprobada_en     TEXT
);
"""


def _fila_a_poliza(fila: sqlite3.Row) -> Poliza:
    return Poliza(
        poliza_id=fila["poliza_id"],
        cliente_id=fila["cliente_id"],
        region=fila["region"],
        producto=fila["producto"],
        suma_asegurada=fila["suma_asegurada"],
        prima_mensual=fila["prima_mensual"],
        estado=EstadoPoliza(fila["estado"]),
        aprobada_por=fila["aprobada_por"],
        aprobada_en=desde_iso_utc(fila["aprobada_en"]) if fila["aprobada_en"] else None,
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

    def contar_polizas(self) -> int:
        with self._transaccion() as conexion:
            fila = conexion.execute("SELECT COUNT(*) AS n FROM polizas").fetchone()
            return int(fila["n"])

    def insertar_polizas(self, polizas: list[Poliza]) -> None:
        with self._transaccion() as conexion:
            conexion.executemany(
                "INSERT INTO polizas (poliza_id, cliente_id, region, producto,"
                " suma_asegurada, prima_mensual, estado) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        p.poliza_id,
                        p.cliente_id,
                        p.region,
                        p.producto,
                        p.suma_asegurada,
                        p.prima_mensual,
                        p.estado.value,
                    )
                    for p in polizas
                ],
            )

    def poliza_por_id(self, poliza_id: str) -> Poliza | None:
        with self._transaccion() as conexion:
            fila = conexion.execute(
                "SELECT * FROM polizas WHERE poliza_id = ?", (poliza_id,)
            ).fetchone()
            return _fila_a_poliza(fila) if fila else None

    def aprobar_poliza(self, poliza_id: str, aprobada_por: str, ahora: datetime) -> Poliza | None:
        """Aprueba la póliza si existe y está `PENDIENTE`.

        Devuelve la póliza actualizada, o `None` si la actualización no afectó
        ninguna fila (no existe, o existe pero no está `PENDIENTE`). El
        llamante distingue ambos casos con `poliza_por_id`.
        """
        with self._transaccion() as conexion:
            cursor = conexion.execute(
                "UPDATE polizas SET estado = ?, aprobada_por = ?, aprobada_en = ?"
                " WHERE poliza_id = ? AND estado = ?",
                (
                    EstadoPoliza.APROBADA.value,
                    aprobada_por,
                    iso_utc(ahora),
                    poliza_id,
                    EstadoPoliza.PENDIENTE.value,
                ),
            )
            if cursor.rowcount == 0:
                return None
            fila = conexion.execute(
                "SELECT * FROM polizas WHERE poliza_id = ?", (poliza_id,)
            ).fetchone()
            return _fila_a_poliza(fila)
