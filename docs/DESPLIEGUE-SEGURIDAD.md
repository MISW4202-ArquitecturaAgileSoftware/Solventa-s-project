# Despliegues de seguridad y disponibilidad

El Compose principal corresponde al experimento de seguridad. Solo incluye
componentes implementados: Redis y Gestión Cotizador, sin puertos públicos.

```bash
docker compose --env-file example.security.env config --quiet
docker compose --env-file example.security.env up -d --wait
```

`example.security.env` usa el proyecto `solventa-security`, separado del
proyecto anterior. No es necesario eliminar volúmenes ni modificar `.env`.
Las redes `data-control` y `data-negocio` son internas; las ACL por servicio
siguen siendo necesarias para restringir el acceso a claves de Redis.
Redis conserva AOF con sincronización cada segundo: no garantiza pérdida cero
ante un fallo abrupto.

## Experimento anterior

Sus servicios y configuración de Redis se conservan. Para ejecutarlo:

```bash
docker compose --env-file example.env -f docker-compose.disponibilidad.yaml config --quiet
docker compose --env-file example.env -f docker-compose.disponibilidad.yaml up -d --wait
```

Los scripts del experimento anterior que llaman a `docker compose` necesitan
seleccionar ese archivo. Con `.env` configurado para disponibilidad:

```bash
COMPOSE_FILE=docker-compose.disponibilidad.yaml ./scripts/preparar.sh
COMPOSE_FILE=docker-compose.disponibilidad.yaml ./scripts/experiment/correr.sh --rapido --sin-pausa
```

Los contenedores existentes y sus volúmenes no se eliminan durante esta migración.

## Gestión Cotizador

El servicio está documentado en [su README](../services/gestion-cotizador/README.md).
Incluye una prueba automática con Redis real, sin depender de los servicios de
autenticación, validación o de una interacción humana.
