"""Punto de entrada para gunicorn: `gunicorn votacion.wsgi:app`."""

from votacion.app import crear_app

app = crear_app()
