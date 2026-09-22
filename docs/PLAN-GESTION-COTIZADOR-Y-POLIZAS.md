# Plan de implementación de Gestión Cotizador y Gestión Pólizas

## Objetivo y punto de partida

Implementar los servicios `gestion-cotizador` y `gestion-polizas` sobre la rama `security`, utilizando como referencia la implementación existente en `seguridad`.

Estado observado al preparar este plan:

- `security`, en `3923b91`, contiene el experimento anterior: `cotizador`, `gestion-errores`, `votacion` y `api-gateway`.
- `seguridad`, en `39d405f`, contiene los dos servicios de referencia y los componentes del experimento de seguridad.
- `gestion-cotizador` y `gestion-polizas` todavía no existen en `security`.

La implementación será una adaptación por etapas de código existente. Los commits y las descripciones de las solicitudes de integración deben identificar la rama y el commit de referencia para mantener clara su procedencia.

## Decisión sobre la limpieza de services

**Conservar inicialmente las carpetas existentes.** Borrar todo `services` eliminaría código reutilizable del cotizador y dejaría referencias rotas en Compose, herramientas y scripts del experimento anterior.

La preparación separará el despliegue anterior del nuevo despliegue de seguridad. Los servicios anteriores pueden permanecer temporalmente en el repositorio sin estar habilitados en el Compose principal de seguridad.

La eliminación de componentes anteriores se realizará posteriormente, en un cambio específico, cuando sus sustitutos y los servicios del resto del equipo estén integrados y se hayan revisado sus referencias. No corresponde incluir esa limpieza general dentro de los commits de estos dos servicios.

## Ramas y secuencia de integración

| Rama | Rama de origen | Destino | Alcance |
|---|---|---|---|
| `chore/security-base` | `security` | `security` | Preparación común del despliegue. |
| `feat/security-gestion-cotizador` | `security`, después de integrar la preparación | `security` | Implementación de Gestión Cotizador. |
| `feat/security-gestion-polizas` | `security`, después de integrar la preparación | `security` | Implementación de Gestión Pólizas. |

```text
security
  └─ chore/security-base ── integración a security

security con la preparación integrada
  ├─ feat/security-gestion-cotizador ── integración a security
  └─ feat/security-gestion-polizas  ── integración a security
```

Ambas ramas de servicio nacen de `security`. Ninguna nace de la rama del otro servicio ni de `seguridad`; esta última se utiliza para consultar y adaptar la implementación de referencia.

Se recomienda trabajar primero Cotizador y después Pólizas. Antes de integrar la segunda rama, incorporar los cambios recientes de `security` y resolver los ajustes compartidos de Compose, configuración y herramientas.

## Preparación común: 1 commit

**Rama:** `chore/security-base`.

**Commit propuesto:**

```text
chore(security): preparar despliegue base para los servicios de seguridad
```

Contenido:

- Conservar el Compose anterior como `docker-compose.disponibilidad.yaml`, con sus referencias válidas.
- Preparar el Compose principal para seguridad, habilitando inicialmente Redis y únicamente los componentes que ya estén disponibles.
- Definir las redes internas `data-control` y `data-negocio`, compatibles con los servicios de referencia, y conectar Redis a ambas.
- Conservar el acceso de los servicios anteriores a Redis cuando se use el despliegue anterior, mediante una configuración compatible o un archivo específico para ese despliegue.
- Mantener Redis sin puerto publicado para el nuevo despliegue.
- Documentar los comandos de arranque de cada experimento y las variables comunes necesarias.
- No incluir en Compose rutas de servicios que todavía no existen.

Validación: resolver ambas configuraciones de Compose y comprobar que el despliegue base de seguridad permite arrancar Redis. No se deben eliminar los volúmenes existentes para preparar esta base.

Esta preparación se integra primero a `security`. Si el equipo ya aporta una base equivalente, se aprovecha ese trabajo y no se duplica el commit.

## Gestión Cotizador: 5 commits

**Rama:** `feat/security-gestion-cotizador`.

**Directorio principal:** `services/gestion-cotizador/`.

| # | Mensaje propuesto | Contenido y resultado verificable |
|---|---|---|
| 1 | `feat(gestion-cotizador): definir contratos y configuracion del servicio` | Paquete Python, dependencias, configuración y contratos de solicitud y respuesta. Pruebas de campos obligatorios, tipos y variables requeridas. |
| 2 | `feat(gestion-cotizador): adaptar calculo de primas y tarifario` | Adaptar `pricing.py`, `tarifario.py` y validaciones de dominio. Preservar cálculos con Decimal y fecha de cálculo recibida. Pruebas de resultados y límites de entrada. |
| 3 | `feat(gestion-cotizador): procesar solicitudes y responder mediante Redis` | Consumir `sol:cotizador`, ejecutar el cálculo y publicar en `resp:{correlation_id}` con expiración. Pruebas del flujo de mensajes y respuestas de error. |
| 4 | `feat(gestion-cotizador): completar ejecucion y manejo de errores del worker` | Punto de entrada, apagado por señal, logs correlacionados y comportamiento ante mensajes inválidos o grupos de consumo inexistentes. Pruebas de los casos correspondientes. |
| 5 | `build(gestion-cotizador): integrar contenedor y documentar ejecucion` | Dockerfile, Compose del servicio, inclusión en el despliegue raíz y ajustes necesarios de herramientas. README y comprobación del recorrido Redis → cálculo → respuesta con el contenedor. |

Comportamiento de referencia:

```text
sol:cotizador
  → consumir solicitud
  → validar y calcular prima
  → publicar respuesta en resp:{correlation_id}
  → confirmar procesamiento
```

Criterios de aceptación:

- Acepta la operación `cotizar` y rechaza operaciones incompatibles con el servicio.
- Conserva el `correlation_id` de la solicitud en la respuesta.
- Utiliza la fecha de cálculo recibida para obtener resultados deterministas.
- Devuelve resultados y errores según los contratos de la rama de referencia.
- Las respuestas tienen un tiempo de vida configurado.
- No publica HTTP ni necesita verificar JWT u OTP: esos controles corresponden al acceso y la validación previos.
- No genera eventos de auditoría de pólizas; su alcance corresponde al cotizador de referencia.

## Gestión Pólizas: 6 commits

**Rama:** `feat/security-gestion-polizas`.

**Directorio principal:** `services/gestion-polizas/`.

| # | Mensaje propuesto | Contenido y resultado verificable |
|---|---|---|
| 1 | `feat(gestion-polizas): definir contratos y configuracion del servicio` | Paquete, dependencias, configuración y contratos de solicitudes, respuestas y auditoría. Pruebas de serialización y validación de mensajes. |
| 2 | `feat(gestion-polizas): implementar repositorio y datos iniciales` | SQLite, esquema, repositorio y semilla de pólizas de referencia. Pruebas de persistencia y de inicialización repetida sin duplicados. |
| 3 | `feat(gestion-polizas): implementar consulta y aprobacion de polizas` | Operaciones `consultar_poliza` y `aprobar_poliza`, transición `PENDIENTE → APROBADA`, empleado y fecha de aprobación. Pruebas de inexistencia y estados inválidos. |
| 4 | `feat(gestion-polizas): consumir solicitudes y publicar respuestas en Redis` | Consumer group de `sol:polizas` y respuestas correlacionadas con expiración. Pruebas del flujo normal y de errores. |
| 5 | `feat(gestion-polizas): publicar auditoria de las operaciones procesadas` | Eventos con actor, recurso, acción, fecha y resultado; correlación y confirmación del procesamiento después de la publicación requerida. Pruebas de contenido y del orden de publicación y confirmación. |
| 6 | `build(gestion-polizas): integrar contenedor y documentar ejecucion` | Punto de entrada, Dockerfile, Compose, volumen de SQLite, configuración y logs de ejecución. Inclusión en el despliegue raíz, README y comprobación con Redis real. |

Comportamiento de referencia:

```text
sol:polizas
  → consumir solicitud
  → consultar o aprobar en SQLite
  → publicar respuesta en resp:{correlation_id}
  → publicar evento en auditoria
  → confirmar procesamiento
```

Criterios de aceptación:

- Consulta una póliza existente y devuelve un error definido si no existe.
- Aprueba solamente pólizas en estado `PENDIENTE`.
- Registra quién aprobó y cuándo.
- Conserva la correlación entre solicitud, respuesta y evento de auditoría.
- Publica auditoría con usuario, recurso, acción, fecha y resultado, sin JWT ni datos financieros completos.
- Persiste los datos en un volumen del servicio.
- No publica puertos HTTP ni implementa los controles de OTP o de emisión de sesiones.

Publicar antes de confirmar el mensaje no garantiza por sí solo atomicidad entre SQLite y Redis. Las mejoras de entrega y recuperación identificadas en la revisión deben tratarse como cambios explícitos, con sus pruebas, si se incorporan a esta implementación.

## Contratos que deben mantenerse compatibles

| Elemento | Acuerdo |
|---|---|
| Solicitud | Sobre con `correlation_id`, tipo, versión, fecha, actor, operación y parámetros. |
| Actor | `employee_id`, `session_id` y `rol`, procedentes del flujo autorizado. |
| Entrada del cotizador | Stream `sol:cotizador`; operación `cotizar`; fecha de cálculo proporcionada. |
| Entrada de pólizas | Stream `sol:polizas`; operaciones `consultar_poliza` y `aprobar_poliza`. |
| Respuestas | Lista `resp:{correlation_id}`, contrato común y TTL configurable. |
| Auditoría | Stream `auditoria`, publicado por Gestión Pólizas. |
| Red de los workers | `data-negocio`, interna y sin puertos publicados. |

La seguridad del productor de mensajes es un requisito de integración. La red interna limita la conectividad, pero no sustituye las ACL de Redis ni permite afirmar que únicamente Validación puede escribir solicitudes.

## Archivos compartidos y responsabilidades

Cada rama modifica principalmente su carpeta de servicio. Los cambios de integración se concentran en su último commit y se limitan a las entradas necesarias en:

- `docker-compose.yaml`.
- `example.env`.
- `pyproject.toml` y scripts de preparación, cuando sea necesario para reconocer el paquete o instalar sus dependencias.

Los cambios generales de Gateway, Autenticación, Validación, OTP y Reacción corresponden a los otros componentes del proyecto. No se trasladará toda la rama `seguridad` para implementar estos dos servicios.

## Verificación e integración

1. Cada commit funcional incluye las pruebas relacionadas y debe dejar su etapa comprobable.
2. Los servicios pueden probarse con productores y consumidores de prueba, sin esperar a que estén implementados todos los demás componentes.
3. Antes de integrar cada rama: ejecutar sus pruebas, formato, análisis estático y tipos aplicables; construir su imagen y comprobar su flujo con Redis real.
4. La prueba de integración debe preparar el consumidor antes de enviar mensajes y esperar resultados con un límite de tiempo definido.
5. Abrir una solicitud de integración por servicio hacia `security`, indicando comportamiento, procedencia del código y verificaciones realizadas.
6. Para conservar visibles los commits de cada etapa, utilizar una estrategia de integración que no los reduzca a un único commit mediante squash.

## Cantidad de commits prevista

| Trabajo | Commits de implementación |
|---|---:|
| Preparación común | 1 |
| Gestión Cotizador | 5 |
| Gestión Pólizas | 6 |
| **Total previsto** | **12** |

Los commits de merge, si se utilizan, no están incluidos en este total. Las cantidades organizan el trabajo por resultados verificables; pueden ajustarse si una corrección real necesita un commit adicional.

Este documento es un plan. Durante su elaboración no se eliminaron servicios, no se crearon ramas de implementación y no se hicieron commits.
