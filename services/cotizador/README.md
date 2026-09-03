# Cotizador

Worker Redis que consume solicitudes, calcula una prima determinística y publica
el resultado. La misma imagen se despliega como las réplicas A, B y C.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
docker build -t solventa/cotizador:dev .
```

El dominio, tarifario, contratos, fallas y pruebas pertenecen a esta carpeta.
