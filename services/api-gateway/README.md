# API Gateway

Puerta HTTP mínima del experimento. Recibe una solicitud, comprueba que tenga
`request_id`, crea un `correlation_id` y la reenvía al servicio configurado. No
calcula, vota, limita peticiones ni conoce la arquitectura interna.

## Endpoints

- `POST /v1/cotizaciones`: reenvía la solicitud y conserva la respuesta HTTP.

## Configuración

- `QUOTATION_SERVICE_URL`: URL completa del servicio que procesa cotizaciones.
- `UPSTREAM_TIMEOUT_MS`: espera máxima de la llamada interna, en milisegundos.
- `LOG_LEVEL`: nivel mínimo del log JSON. Las respuestas normales se registran
  como `INFO`, los timeouts y respuestas inválidas como `WARNING`, y las caídas
  de conexión como `ERROR`.

## Desarrollo

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
docker build -t solventa/api-gateway:dev .
```

Todo el código requerido para construir y probar la imagen vive en esta carpeta.
