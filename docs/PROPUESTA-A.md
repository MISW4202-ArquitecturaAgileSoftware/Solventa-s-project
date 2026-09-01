# Propuesta A

Bitácora de las decisiones y cambios realizados sobre la propuesta original del
experimento. Este documento se actualizará junto con cada cambio relevante.

## Objetivo

Mantener una arquitectura experimental sencilla, comprensible y fácil de
modificar. Se prioriza que cada servicio sea autónomo a nivel de desarrollo,
pruebas y construcción Docker, aun cuando esto implique duplicar una cantidad
pequeña de contratos y utilidades.

## Cambios realizados

### 1. Servicios autocontenidos

- Se eliminó la dependencia de código fuente `libs/solventa-common`.
- Cada servicio conserva localmente los contratos y utilidades que necesita.
- El cálculo, tarifario y sus pruebas quedaron bajo la responsabilidad del
  servicio Cotizador.
- El generador del experimento conserva un oráculo local para verificar la prima
  esperada sin importar código de otro servicio.

### 2. Construcción Docker aislada

- Cada Dockerfile usa la carpeta del servicio como contexto de construcción.
- Ninguna imagen necesita leer archivos de otra carpeta del repositorio.
- Cada servicio incluye su propio `.dockerignore`.

### 3. Desarrollo independiente

Cada servicio incluye:

- `requirements.txt` para ejecución.
- `requirements-dev.txt` para pruebas locales.
- `README.md` con los comandos básicos.
- Su código fuente y su suite de pruebas.

### 4. Validación

- 193 pruebas aprobadas.
- Configuración de Docker Compose válida.
- Imágenes de API Gateway, Voting, Cotizador y Gestor de Errores construidas
  usando contextos aislados.
- Stack completo levantado con todos los contenedores saludables.
- Cotización extremo a extremo verificada con prima mensual `90348.41`.

## Estado actual

La autonomía de los servicios conserva el comportamiento funcional de la
propuesta original. Los siguientes cambios de la Propuesta A se documentarán en
nuevas secciones y commits separados.
