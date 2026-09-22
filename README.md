# Solventa — Experimento de seguridad (ASR-23 / ASR-31)

Monorepo de microservicios Python que materializa el experimento **"Detección y
reacción ante elevación de privilegios y divulgación de información"** del
módulo 7 (Seguridad) de Arquitecturas Ágiles de Software, sobre el caso de
estudio Solventa (aseguradora: cotizaciones y pólizas).

## 1. Contexto del experimento

Solventa procesa operaciones de negocio (cotizar, consultar y aprobar pólizas)
que ejecutan empleados con distintos roles y alcances regionales. El
experimento evalúa si la arquitectura propuesta es capaz de **detectar** dos
tipos de incidente y **reaccionar** revocando el acceso y generando una
alerta, con la particularidad de que la reacción viaja por una cola de
mensajes (procesamiento asíncrono).

**Hipótesis de diseño.** El estilo de microservicios con mensajería asíncrona
favorece la modificabilidad y la disponibilidad al desacoplar detección y
reacción, pero puede **retrasar la revocación** y permitir una segunda
operación no autorizada. El experimento mide exactamente ese riesgo.

### ASR bajo prueba

| ASR | Atributo | Escenario | Respuesta esperada del sistema |
|---|---|---|---|
| **ASR-23** | Integridad | Un atacante altera el rol de un empleado (asesor → supervisor) e intenta una operación privilegiada (aprobar una póliza). | Detectar el uso de privilegios superiores a los autorizados, impedir la operación y **bloquear una segunda operación**. |
| **ASR-31** | Confidencialidad | Un empleado con sesión legítima consulta pólizas de una región **fuera de su alcance**. | Detectar la consulta fuera de alcance, revocar el acceso, generar una alerta e **impedir una segunda consulta**. |

### Tácticas de seguridad implementadas

- **Autenticar actores**: sesiones JWT emitidas y verificadas solo por `autenticacion`.
- **Autorizar operaciones**: `validacion` contrasta cada solicitud con su registro independiente de permisos por rol.
- **Verificación adicional (OTP)**: la primera operación con un rol distinto al último observado exige un código de un solo uso enviado por un canal que el atacante no controla. Un intento fallido dispara la reacción.
- **Detectar intrusiones a posteriori**: `auditor` revisa periódicamente los eventos de auditoría y contrasta la región consultada con el historial de cada empleado.
- **Revocar acceso y notificar**: Reacción, un proceso interno de `validacion`, consume los eventos de seguridad, revoca la sesión, bloquea al empleado y registra la alerta de forma idempotente.
- **Limitar exposición**: el `api-gateway` es el único servicio con salida al exterior; los workers de negocio solo alcanzan la cola.

## 2. Arquitectura

```
cliente ──► api-gateway ──► autenticacion (verificar sesión)
                │
                └──► validacion ──► [Redis] sol:polizas ──► gestion-polizas ──► [Redis] auditoria ──► auditor
                       │  ▲                 sol:cotizador ──► gestion-cotizador                          │
                       │  └──────────────── resp:{correlation_id} ◄───────────────┘                      │ POST /v1/anomalias
                       │                                                                                 ▼
                       └──► [Redis] seguridad ──► validacion (hilo Reacción) ──► autenticacion (revocar + bloquear)
```

| Servicio | Tipo | Responsabilidad |
|---|---|---|
| `api-gateway` | Flask | Única puerta pública. Verifica la sesión con Autenticación y enruta a Validación. Sin lógica de negocio. |
| `autenticacion` | Flask + SQLite | Login (JWT HS256), verificación, revocación de sesiones y bloqueo de empleados. |
| `validacion` (incluye Reacción) | Flask + SQLite + Redis | Autoriza por rol, retiene con OTP ante cambio de rol, encola hacia negocio, decide sobre anomalías. Su hilo de Reacción consume `seguridad`, revoca, bloquea y registra alertas sin duplicados. |
| `gestion-polizas` | worker + SQLite | Consulta y aprobación de pólizas. Publica un evento de auditoría por operación. |
| `gestion-cotizador` | worker | Cálculo determinista de primas (carga de fondo). |
| `auditor` | worker + SQLite | Cada `PERIODO_AUDITORIA_S` contrasta los eventos de auditoría con el historial e informa anomalías. |
| `redis` | cola | Streams (`sol:*`, `auditoria`, `seguridad`) y listas de respuesta. |

Cada servicio es **autocontenido** (contratos, cliente de Redis, logging y
semillas dentro de su carpeta; no hay librería compartida) y vive en
`services/<servicio>/` con su propio `Dockerfile`, `docker-compose.yaml`,
`requirements.txt`, código y tests. El `docker-compose.yaml` de la raíz solo
los agrupa con `include:` y declara las redes.

Las redes garantizan el aislamiento: el plano de negocio (`data-negocio`) y el
de control (`data-control`) solo comparten a Redis, así que un worker de
negocio no puede alcanzar por HTTP a Validación ni a Autenticación, y por eso
los workers pueden confiar en lo que llega por la cola.

## 3. Requisitos

- Docker y Docker Compose v2 (con soporte de `include:`).
- Python 3.14 (el proyecto fija `3.14.6` en `.python-version`).
- `curl` para las pruebas manuales.
- Puertos libres en el host: `8000` (gateway), `8001` (autenticación), `8002` (validación), `8089` (Locust).

## 4. Puesta en marcha

```bash
cp example.env .env          # ajustar puertos si alguno está ocupado
./scripts/preparar.sh        # venv, imágenes, stack arriba y journey de humo
```

`preparar.sh` termina con un login del supervisor y una consulta de póliza por
el gateway. Otros scripts útiles:

| Script | Uso |
|---|---|
| `./scripts/up.sh` / `./scripts/down.sh [-v]` | Levantar / detener el stack (`-v` borra los datos y vuelve a las semillas). |
| `./scripts/logs.sh [servicio]` | Logs JSON con `correlation_id`. |
| `./scripts/test.sh` | `ruff` + `mypy --strict` + `pytest` de todo el monorepo. |
| `./scripts/config.sh` | Ver el Compose resuelto. |

### Datos de prueba

Todos los empleados usan la contraseña `solventa`.

| Usuario | Rol | Alcance | Papel |
|---|---|---|---|
| `asesor.norte.01` … `10` | asesor | norte | Víctimas de ASR-23 y atacantes de ASR-31 |
| `asesor.mixto.01`, `02` | asesor | norte, centro | Caso legítimo inusual (control de falsos positivos) |
| `supervisor.01` | supervisor | norte, sur, centro | Control: aprueba sin OTP y verifica estados |

Pólizas: `POL-NOR-001..020`, `POL-SUR-001..020`, `POL-CEN-001..020`; las
`001..010` de cada región nacen `PENDIENTE` (aprobables).

## 5. Ejecutar el experimento

```bash
./scripts/experiment/correr.sh --rapido     # 1 corrida, PERIODO_AUDITORIA_S=2  (~1 min)
./scripts/experiment/correr.sh              # corrida oficial: periodos 2,5,10 × 5 repeticiones (~20 min)
./scripts/experiment/correr.sh --periodos 5 --repeticiones 3
```

Cada repetición **reinicia el stack desde cero** (`docker compose down -v &&
up --wait`), porque un empleado revocado no se puede reutilizar, y luego
ejecuta:

1. **Atacante ASR-23** (`asesor.norte.01`): altera su rol a `supervisor` vía el endpoint de experimento de Autenticación, inicia sesión, pide aprobar `POL-NOR-001` → `202 OTP_REQUERIDO`; envía un código inventado → `403 otp-fallido`; reintenta la aprobación → `401 sesion-revocada`. Mide la latencia entre el 403 y el primer 401.
2. **Legítimo ASR-23** (`asesor.norte.02`): igual, pero lee el código real del canal simulado (`GET /v1/experimento/otp/{session_id}` en Validación) → `200` y la póliza queda `APROBADA`.
3. **Atacante ASR-31 secuencial** (`asesor.norte.03`): consulta una póliza de `sur` → `200`; espera un ciclo del Auditor; consulta otra → `401 sesion-revocada`.
4. **Legítimo inusual ASR-31** (`asesor.mixto.01`): consulta `centro` (autorizado pero nunca usado) → `200`; tras el ciclo sigue `200` y hay alerta `CONSULTA_INUSUAL` sin revocación.
5. **Ráfaga concurrente con Locust**: cinco atacantes (`asesor.norte.04..08`) consultan pólizas de `sur` cada 100 ms hasta ser revocados, con tres usuarios habituales de fondo. De aquí sale la **ventana de exposición**.
6. Vuelca las alertas de Reacción (`GET http://localhost:8002/v1/alertas`) y verifica como `supervisor.01` que `POL-NOR-001` sigue `PENDIENTE` y `POL-NOR-002` quedó `APROBADA`.

La evidencia cruda queda en `scripts/experiment/resultados/<timestamp>/`
(un JSON por corrida, JSONL y CSV de Locust) y el informe se genera en
`docs/RESULTADOS-EXPERIMENTO.md`.

### Endpoints de experimento

Existen solo con `MODO_EXPERIMENTO=true` y solo en la red `ops`; simulan lo
que en la realidad harían el atacante y el canal OTP legítimo:

- `PUT http://localhost:8001/v1/experimento/empleados/{employee_id}/rol` `{ "rol": "supervisor" }` — la alteración del atacante.
- `GET http://localhost:8002/v1/experimento/otp/{session_id}` — el código que el empleado legítimo recibiría por SMS o correo.

## 6. Resultados esperados

| ASR | Métrica | Umbral |
|---|---|---|
| 23 | Detección de OTP fallidos | 100 % |
| 23 | Operaciones privilegiadas ejecutadas sin OTP correcto | 0 |
| 23 | Segunda operación bloqueada (`401 sesion-revocada`) | 100 % |
| 23 | Latencia de revocación (403 → primer 401) | reportar p50 / p95 |
| 31 | Detección de consultas fuera de alcance | 100 % |
| 31 | Falsos positivos (revocaciones a legítimos) | 0, con alerta `CONSULTA_INUSUAL` |
| 31 | Segunda consulta secuencial bloqueada | 100 % |
| 31 | Ventana de exposición (consultas `200` y ms antes del primer `401`) | reportar por `PERIODO_AUDITORIA_S` |
| ambos | Alertas registradas duplicadas | 0 |

El resultado central de la hipótesis es la **ventana de exposición** de
ASR-31: con detección a posteriori, la primera consulta indebida siempre se
sirve, y lo que se mide es cuánto se fuga antes de que la reacción asíncrona
surta efecto.

## 7. Resultados obtenidos (corrida oficial)

15 corridas (`PERIODO_AUDITORIA_S ∈ {2, 5, 10}` × 5 repeticiones). Detalle en
`docs/RESULTADOS-EXPERIMENTO.md`.

| Métrica | Observado |
|---|---|
| ASR-23 · detección / operaciones sin OTP / segunda operación bloqueada | 100 % / 0 / 100 % |
| ASR-23 · latencia de revocación | p50 132 ms · p95 148 ms |
| ASR-31 · detección / falsos positivos / segunda consulta bloqueada (atacante lento, espera > P) | 100 % / 0 / 100 % |
| Alertas registradas duplicadas | 0 (3 108 eventos redundantes absorbidos por idempotencia) |

| `PERIODO_AUDITORIA_S` | Ventana p50 | Ventana p95 | Consultas `200` antes del `401` |
|---|---|---|---|
| 2 s | 1 111 ms | 1 317 ms | 9,7 |
| 5 s | 4 013 ms | 4 155 ms | 35,7 |
| 10 s | 9 166 ms | 9 795 ms | 82,0 |

**Conclusión.** La detección se cumple al 100 % en ambos ASR, sin falsos
positivos, y la reacción (evento → revocación) cuesta ~130 ms. El bloqueo de la
segunda operación se cumple **estrictamente en ASR-23**: la operación se
retiene antes de ejecutarse y el atacante no ejecuta ni una. En **ASR-31 se
cumple solo condicionalmente**: la detección es a posteriori, así que la
primera consulta indebida siempre se sirve y también todas las que lleguen
antes del siguiente ciclo del Auditor. Un atacante lento (espera más de `P`
entre consultas) es bloqueado en la segunda; uno rápido obtiene ≈ `P × 9`
pólizas ajenas antes del primer `401` (10, 36 y 82 para P = 2, 5 y 10 s). Esa
ventana de exposición, que crece linealmente con `P`, es el coste medible del
estilo asíncrono que la hipótesis ponía a prueba: reducir el periodo la
acorta, pero no la elimina. Las ventanas medidas son conservadoras (cercanas
al peor caso) porque el protocolo determinista hace que la ráfaga arranque
justo después de un ciclo del Auditor. Detalle en `docs/RESULTADOS-EXPERIMENTO.md`.

## 8. Prueba manual del journey

```bash
G=localhost:8000; A=localhost:8001; J='content-type: application/json'
login() { curl -s -XPOST $G/v1/sesiones -H "$J" -d "{\"usuario\":\"$1\",\"password\":\"solventa\"}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])'; }

# ASR-23
curl -s -XPUT $A/v1/experimento/empleados/E-ASN-04/rol -H "$J" -d '{"rol":"supervisor"}'
T=$(login asesor.norte.04)
curl -si -XPOST $G/v1/polizas/POL-NOR-003/aprobacion -H "authorization: Bearer $T" | head -1   # 202
curl -si -XPOST $G/v1/otp -H "authorization: Bearer $T" -H "$J" -d '{"codigo":"000000"}' | head -1   # 403
sleep 1
curl -si -XPOST $G/v1/polizas/POL-NOR-003/aprobacion -H "authorization: Bearer $T" | head -1   # 401

# ASR-31
T=$(login asesor.norte.05)
curl -si $G/v1/polizas/POL-SUR-002 -H "authorization: Bearer $T" | head -1   # 200
sleep 8                                                                     # > PERIODO_AUDITORIA_S
curl -si $G/v1/polizas/POL-SUR-003 -H "authorization: Bearer $T" | head -1   # 401

curl -s localhost:8002/v1/alertas | python3 -m json.tool
```

## 9. Limitaciones conocidas

- El OTP admite **un solo intento** y **no vence**: un legítimo que se equivoque queda revocado; una sesión con OTP pendiente permanece retenida. Ambas son decisiones del experimento.
- El modelo de amenaza de ASR-23 es un atacante externo que se apropió de la cuenta; un insider que se eleva su propio rol y controla su canal OTP queda fuera del alcance.
- Redis es punto único de falla; aceptado para el experimento.
- Los tags de imagen (`redis:8.10-alpine`, `dev`) son flotantes; para reproducibilidad estricta conviene fijarlos.

## 10. Estructura del repositorio

```
docker-compose.yaml        include: de cada servicio + redes compartidas
example.env                contrato de configuración (copiar a .env)
queue-service/             Redis (imagen oficial + redis.conf)
services/<servicio>/       Dockerfile, docker-compose.yaml, requirements, src/, tests/, README.md
scripts/                   up, down, build, logs, test, config, bootstrap, preparar
scripts/experiment/        correr.sh, reiniciar.sh, escenarios, locustfile, métricas, reporte
docs/                      ejemplos de cuerpos y RESULTADOS-EXPERIMENTO.md
```
