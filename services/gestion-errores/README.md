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

Expone `POST /v1/incidentes`, `GET /v1/incidentes`, `GET /v1/incidentes/reporte`
y `GET /v1/metricas`.

## Reporte HTML

`GET /v1/incidentes/reporte` devuelve el mismo histórico que `GET /v1/incidentes`,
pero como página HTML pensada para personas: resumen ejecutivo (total, por tipo
y por réplica divergente) y una ficha por incidente, del más reciente al más
antiguo, que responde tres preguntas:

- **Qué**: tipo de incidente con su explicación, réplicas fuera del consenso,
  campos del resultado en los que hubo diferencias y el detalle que redactó
  Votación.
- **Cuándo**: instante de detección en UTC, legible y en ISO-8601, junto al
  `correlation_id` del journey.
- **Cómo**: estado de cada réplica (respondió o falló, y con qué error) y una
  tabla campo × réplica con los valores devueltos, resaltando los que difieren
  del valor mayoritario.

Acepta los mismos filtros que el JSON: `?correlation_id=` para un journey y
`?limite=` (100 por defecto) para el histórico reciente. No carga recursos
externos, así que se puede abrir desde la red `ops` sin salida a Internet e
imprimir directamente.
