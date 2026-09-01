"""Punto de entrada para gunicorn: `gunicorn gestion_errores.wsgi:app`."""

from gestion_errores.app import crear_app

app = crear_app()
