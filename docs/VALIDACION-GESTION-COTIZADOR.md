# Validación de Gestión Cotizador

Implementación en `feat/security-gestion-cotizador`, creada desde `security`
después de integrar localmente la preparación `eb0086e`. Código de referencia:
`seguridad`, commit `39d405f`.

## Alcance implementado

- Contratos locales y configuración del servicio.
- Cálculo determinista de primas con Decimal y tarifario versionado.
- Solicitudes desde `sol:cotizador` y respuestas con correlación y TTL.
- Errores de validación y manejo de mensajes corruptos sin detener el bucle.
- Arranque, logs correlacionados y apagado limpio.
- Contenedor sin privilegios y sin puertos publicados.
- Prueba automática con Redis real, independiente de Gateway y Validación.

El despliegue anterior se conserva en `docker-compose.disponibilidad.yaml`.
No se modificaron sus servicios ni sus volúmenes. El nuevo proyecto utiliza
`example.security.env` y un espacio de nombres distinto.

## Verificaciones realizadas

| Verificación | Resultado |
|---|---|
| Pruebas del nuevo servicio | 79 aprobadas, con las dependencias declaradas instaladas en un entorno temporal. |
| Suite completa del repositorio | 291 aprobadas con el entorno local existente. Un aviso de Locust/gevent sobre el orden de importación de SSL. |
| Ruff y formato del nuevo servicio | Correctos. |
| Mypy del nuevo servicio, pruebas y script de integración | Sin errores. |
| Compose de seguridad y Compose anterior | Ambas configuraciones se resuelven correctamente. |
| Exposición del Compose de seguridad | Redis y Gestión Cotizador sin puertos publicados. |
| Construcción Docker | Imagen `solventa/gestion-cotizador:dev` construida. |
| Integración con Redis real | Cuatro solicitudes procesadas con correlación, TTL y XACK correctos. |
| Detención del worker | Salida limpia con código `0`. |

Los dos casos válidos dieron prima mensual `90348.41` y anual `1084180.92`,
con idéntico resultado para los mismos datos y fecha. Los casos de operación
incompatible e importe fuera de rango devolvieron `ERROR/VALIDACION`.

La prueba integrada se ejecutó en el proyecto temporal
`solventa-cotizador-check`, separado de los despliegues existentes. No se
utilizaron cuentas de usuario ni se probaron JWT u OTP: están fuera del alcance
de este worker.

## Repetir la integración

Desde la raíz del repositorio:

```bash
docker compose --env-file example.security.env up -d --build --wait redis gestion-cotizador
docker compose --env-file example.security.env exec -T gestion-cotizador python - \
  < services/gestion-cotizador/scripts/verificar_redis.py
```

El script espera a que el grupo esté listo antes de publicar. No requiere pasos
manuales y no vacía Redis. Ver configuración, contratos y límites de recuperación
en el [README del servicio](../services/gestion-cotizador/README.md).

## Estado de integración

La preparación común está incorporada a `security` localmente. Los cinco commits
del cotizador permanecen en su rama para revisión e integración posterior. No se
publicaron ramas ni se creó una solicitud de integración remota durante este
trabajo.
