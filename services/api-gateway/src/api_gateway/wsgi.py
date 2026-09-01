"""Punto de entrada para gunicorn: `gunicorn api_gateway.wsgi:app`."""

from api_gateway.app import crear_app

app = crear_app()
