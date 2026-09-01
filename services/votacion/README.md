# Servicio de Votación

Publica solicitudes en Redis, reúne respuestas correlacionadas y aplica la
mayoría configurada. Reporta las inconsistencias fuera del camino crítico.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
docker build -t solventa/votacion:dev .
```

Todo el código requerido para construir y probar la imagen vive en esta carpeta.
