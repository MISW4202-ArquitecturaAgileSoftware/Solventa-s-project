"""Logging estructurado en JSON con `correlation_id` obligatorio.

El experimento se audita leyendo logs: si una línea no lleva `correlation_id`,
no se puede atribuir a un journey y es ruido. El identificador se propaga por
`ContextVar`, de modo que las funciones de dominio no tienen que recibirlo como
parámetro ni conocer el logger.

El nombre `structured_logging` lo distingue del módulo `logging` de la
biblioteca estándar y explica el formato que produce.
"""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Atributos que LogRecord trae de serie; todo lo demás que traiga el record es
# contexto que el llamante añadió con `extra=` y va al JSON.
_ATRIBUTOS_ESTANDAR = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__)


def fijar_correlation_id(valor: str | None) -> None:
    _correlation_id.set(valor)


def correlation_id_actual() -> str | None:
    return _correlation_id.get()


@contextmanager
def contexto_correlacion(valor: str) -> Iterator[None]:
    """Asocia todas las líneas emitidas dentro del bloque a un journey."""
    testigo = _correlation_id.set(valor)
    try:
        yield
    finally:
        _correlation_id.reset(testigo)


class FormateadorJson(logging.Formatter):
    def __init__(self, servicio: str) -> None:
        super().__init__()
        self.servicio = servicio

    def format(self, record: logging.LogRecord) -> str:
        linea: dict[str, Any] = {
            "momento": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%03dZ"),
            "nivel": record.levelname,
            "servicio": self.servicio,
            "logger": record.name,
            "mensaje": record.getMessage(),
            "correlation_id": correlation_id_actual(),
        }
        for clave, valor in record.__dict__.items():
            if clave not in _ATRIBUTOS_ESTANDAR and not clave.startswith("_"):
                linea[clave] = valor
        if record.exc_info is not None:
            linea["excepcion"] = self.formatException(record.exc_info)
        return json.dumps(linea, ensure_ascii=False, default=str)


def configurar(servicio: str, nivel: str = "INFO") -> None:
    """Deja un único handler a stdout con formato JSON.

    A stdout y no a un archivo: en un contenedor los logs son un flujo, y de
    recogerlos se encarga el runtime.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(FormateadorJson(servicio))
    raiz = logging.getLogger()
    raiz.handlers.clear()
    raiz.addHandler(handler)
    raiz.setLevel(nivel.upper())
