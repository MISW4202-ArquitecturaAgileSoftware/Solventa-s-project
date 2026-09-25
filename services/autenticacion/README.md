# Autenticación

Emite sesiones (JWT HS256), las verifica y ejecuta la contención que ordena
Reacción (el proceso de contención que vive dentro de Validación): revocar una
sesión y bloquear a un empleado. Es el único servicio que
conoce `JWT_SECRET`; para el resto el token es opaco.

## Endpoints

- `POST /v1/sesiones` — login; `201` con `token`, `session_id`, `employee_id`, `rol`.
- `POST /v1/sesiones/verificar` — `{ token }` → `{ valida, motivo?, employee_id?, session_id?, rol? }`.
  Nunca responde 401: el gateway necesita el motivo (`INVALIDA | EXPIRADA | REVOCADA | BLOQUEADO`).
- `POST /v1/sesiones/{session_id}/revocacion` — idempotente.
- `POST /v1/empleados/{employee_id}/bloqueo` — idempotente; invalida las sesiones vivas en la verificación.
- `PUT /v1/experimento/empleados/{employee_id}/rol` — solo con `MODO_EXPERIMENTO=true`. Simula al
  atacante que altera el rol en la base. El token vigente no cambia: hace falta un login nuevo.
- `GET /health`.

## Configuración

- `RUTA_DB` (por defecto `/data/autenticacion.db`), `JWT_SECRET`, `JWT_TTL_S`,
  `MODO_EXPERIMENTO`, `LOG_LEVEL`.

## Datos

Siembra los 13 empleados de `PLAN-IMPLEMENTACION.md` §2.2 si la base está vacía.
Contraseña de todos: `solventa` (scrypt con sal).

## Desarrollo

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python -m pytest -q tests
docker build -t solventa/autenticacion:dev .
```
