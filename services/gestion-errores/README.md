# Gestor de Errores

Recibe los incidentes detectados por Votación y los persiste como evidencia
JSONL del experimento mediante un escritor asíncrono.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
docker build -t solventa/gestion-errores:dev .
```

Todo el código requerido para construir y probar la imagen vive en esta carpeta.
