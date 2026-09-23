# Autenticación

Emite y verifica las sesiones de los empleados (JWT HS256 con PyJWT) y las
invalida cuando Reacción lo pide. Es el **único** servicio que conoce
`JWT_SECRET`: para el gateway y Validación el token es opaco. No usa la cola:
solo se conecta a `backend` y, para el experimento, a `ops`.

## Endpoints

- `POST /v1/sesiones` — login. `201` con `session_id`, `employee_id`, `rol`,
  `token` y `expira_en`. `401 credenciales` si el usuario o la contraseña no
  coinciden (mismo mensaje y mismo coste de scrypt en ambos casos, para no
  revelar qué usuarios existen); `401 empleado-bloqueado` si la contraseña es
  correcta pero el empleado está bloqueado; `422` si el cuerpo es inválido.
- `POST /v1/sesiones/verificar` — §5.6. **Nunca responde 401**: devuelve `200`
  con `valida: true` y el actor, o `valida: false` con `motivo` ∈
  `INVALIDA | EXPIRADA | REVOCADA | BLOQUEADO`, en ese orden de evaluación. El
  `rol` es el del claim, es decir, el que tenía el empleado al iniciar sesión.
  Un token bien firmado cuya sesión no existe (p. ej. de una corrida anterior
  a un `down -v`) es `INVALIDA`.
- `POST /v1/sesiones/{session_id}/revocacion` — idempotente y atómico: si la
  sesión ya estaba revocada responde `200` con `ya_estaba_revocada: true` y el
  instante original. `404` si la sesión no existe.
- `POST /v1/empleados/{employee_id}/bloqueo` — idempotente. Bloquea nuevos
  logins e invalida en la verificación todas las sesiones vivas del empleado,
  sin tocar la tabla `sesiones` (así el motivo `REVOCADA` sigue significando
  una revocación explícita). `sesiones_afectadas` cuenta las sesiones no
  revocadas ni expiradas en ese instante; es `0` si ya estaba bloqueado.
- `PUT /v1/experimento/empleados/{employee_id}/rol` — la alteración del
  atacante: cambia `empleados.rol` y nada más. Solo existe con
  `MODO_EXPERIMENTO=true`; sin él, `404`.
- `GET /health`.

Revocación y bloqueo exigen `motivo`, `correlation_id` y `evento_id` en el
cuerpo; el `correlation_id` del cuerpo pasa a ser el del log y el de la
cabecera `X-Correlation-Id` de la respuesta. Los errores son RFC 9457
(`application/problem+json`); los que no tienen semántica propia (ruta
inexistente, método no admitido) usan `type: about:blank`.

## Configuración

`JWT_SECRET` (obligatoria, **mínimo 32 bytes**: RFC 7518 §3.2 para HS256; el
servicio no arranca con uno más corto), `JWT_TTL_S` (`3600`), `RUTA_DB` (por
defecto `/data/autenticacion.db`), `MODO_EXPERIMENTO` (`false`), `LOG_LEVEL`.

## Datos

Siembra los 13 empleados de §2.2 si la base está vacía. Contraseñas con
`hashlib.scrypt` (n=2¹⁴, r=8, p=1) y sal propia por empleado, guardadas como
`scrypt$n$r$p$sal$derivada`. Las sesiones nacen con cada login. No hay
desbloqueo: el estado se reinicia con `docker compose down -v`.

## Desarrollo

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python -m pytest -q tests
docker build -t solventa/autenticacion:dev .
```

Los tests usan un reloj inyectable (`crear_app(reloj=...)`) para probar la
expiración sin esperar, y siembran la base una sola vez por sesión de pytest
porque scrypt cuesta ~35 ms por empleado.
