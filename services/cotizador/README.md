# Cotizador

Worker Redis que consume solicitudes, calcula una prima determinística y publica
el resultado. La misma imagen se despliega como las réplicas A, B y C.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
docker build -t solventa/cotizador:dev .
```

El dominio, tarifario, contratos, fallas y pruebas pertenecen a esta carpeta.

El worker tiene un único recorrido:

```text
Redis -> leer solicitud -> calcular -> aplicar fallo configurado -> responder
```

`contracts.py` solo implementa las direcciones usadas aquí: deserializa la
solicitud y serializa la respuesta. El worker no expone servidor HTTP ni
healthcheck; las corridas comienzan después de levantar el stack controlado.

Las reglas que intentaban juzgar si el resultado calculado era razonable no
pertenecen al worker. Los fallos se entregan deliberadamente para que Votación
los detecte comparando las tres respuestas.
