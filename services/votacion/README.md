# Servicio de Votación

Implementa la táctica de votación del experimento. Publica una solicitud en
Redis, reúne una respuesta diferente por cotizador y entrega un resultado solo
cuando al menos dos primas mensuales coinciden.

## Flujo

1. Recibe `POST /v1/cotizaciones` desde el API Gateway.
2. Fija una única fecha de cálculo para las tres réplicas.
3. Publica una vez en el stream de Redis; los consumer groups hacen el fan-out.
4. Recoge respuestas con un presupuesto global y una ventana corta de gracia.
5. Descarta respuestas ilegibles, duplicadas o de otra correlación.
6. Agrupa directamente las respuestas por el resultado funcional completo:
   cotización, versión del tarifario y explicación del cálculo.
7. Responde únicamente si existe quórum y reporta cualquier incidente fuera del
   camino crítico.

Votación no contiene la fórmula, las tablas del tarifario ni validaciones de
negocio. Es un coordinador: compara, cuenta y decide. Solo comprueba aspectos
técnicos como correlación, identidad de la réplica y presencia de una respuesta.

Los módulos pertenecen directamente al paquete `votacion/`. No existe una
carpeta `common` porque los contratos, errores, identificadores y logs
son propios de este servicio, no una biblioteca compartida.

## Decisión sin quórum

Una sola respuesta válida no es suficiente para confirmar una cotización. Si
no hay dos resultados coincidentes, el servicio responde `RECHAZADO` en lugar
de entregar un valor degradado sin segunda opinión.

La táctica supone que como máximo una de las tres réplicas falla. Si dos
cotizadores entregan el mismo valor incorrecto, ese valor formará mayoría; un
servicio de votación puro no conoce la fórmula para determinar lo contrario.

## Desarrollo

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
docker build -t solventa/votacion:dev .
```

Todo el código requerido para construir y probar la imagen vive en esta carpeta.
