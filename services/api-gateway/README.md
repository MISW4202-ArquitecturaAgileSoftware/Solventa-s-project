# api-gateway

La única puerta pública del sistema. Enruta hacia Autenticación y Validación;
no interpreta el token, no conoce roles ni alcances y no tiene lógica de
negocio propia.

## Flujo por petición protegida

1. Genera `correlation_id` (UUIDv7), uno por petición pública (§1.4).
2. Lee `Authorization: Bearer <token>`; ausente o malformado → `401
   sesion-invalida`, sin llamar a Autenticación.
3. `POST autenticacion/v1/sesiones/verificar`. Según `motivo`: `INVALIDA` o
   `EXPIRADA` → `401 sesion-invalida`; `REVOCADA` → `401 sesion-revocada`;
   `BLOQUEADO` → `401 empleado-bloqueado`.
4. Con sesión válida arma el `actor` (`employee_id`, `session_id`, `rol`) y
   llama a Validación.
5. Propaga estado, cuerpo y `Content-Type` de Validación tal cual.

Toda respuesta lleva `X-Correlation-Id`.

## Endpoints

- `POST /v1/sesiones` — reenvía el cuerpo tal cual a Autenticación; no requiere Bearer.
- `POST /v1/otp` (Bearer) — `{ codigo }` → Validación `{ correlation_id, session_id, codigo }`.
- `GET /v1/polizas/{poliza_id}` (Bearer) — operación `consultar_poliza`.
- `POST /v1/polizas/{poliza_id}/aprobacion` (Bearer) — operación `aprobar_poliza`.
- `POST /v1/cotizaciones` (Bearer) — operación `cotizar`; el cuerpo es `parametros` tal cual (debe ser un objeto JSON).
- `GET /health`.

## Errores que origina

`validacion` 422 (cuerpo propio malformado), `sesion-invalida` 401,
`sesion-revocada` 401, `empleado-bloqueado` 401, `upstream` 502/503/504 (el
servicio interno responde basura, rechaza la conexión o no responde en
`UPSTREAM_TIMEOUT_MS`). El resto de errores (403, 404, 409, 422 de negocio…)
se propagan tal cual desde Autenticación o Validación, con su
`application/problem+json` íntegro.

## Configuración

`URL_AUTENTICACION`, `URL_VALIDACION` (obligatorias), `UPSTREAM_TIMEOUT_MS`
(por defecto `3000`), `LOG_LEVEL`.

## Desarrollo

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python -m pytest -q tests
docker build -t solventa/api-gateway:dev .
```
