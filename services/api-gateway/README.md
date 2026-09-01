# API Gateway

Puerta HTTP del experimento. Genera la correlación, aplica el límite de tasa y
delega la cotización al servicio configurado. No calcula ni vota.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
docker build -t solventa/api-gateway:dev .
```

Todo el código requerido para construir y probar la imagen vive en esta carpeta.
