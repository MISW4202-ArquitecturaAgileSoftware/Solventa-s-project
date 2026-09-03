# Gestor de Errores

Recibe los incidentes detectados por Votación y los persiste como evidencia
JSONL antes de responder `201 Created`. Votación realiza el envío en segundo
plano, por lo que este servicio no necesita otra cola interna.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
docker build -t solventa/gestion-errores:dev .
```

Todo el código requerido para construir y probar la imagen vive en esta carpeta.

Expone únicamente `POST /v1/incidentes`, `GET /v1/incidentes` y
`GET /v1/metricas`.
