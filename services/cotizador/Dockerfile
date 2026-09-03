# syntax=docker/dockerfile:1
#
# Réplica del cotizador. Una sola imagen para A, B y C: lo único que las
# distingue es COTIZADOR_ID y FAULT_MODE en tiempo de ejecución.
#
# El contexto de build es esta misma carpeta; no depende de archivos externos.

# --- Etapa de construcción ---------------------------------------------------
FROM python:3.14.6-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_COMPILE=1

# Entorno virtual aislado: se copia entero a la imagen final y así no viajan ni
# pip, ni setuptools, ni la caché de ruedas.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Ordenado por volatilidad: primero el manifiesto de dependencias, que cambia
# poco; el código va después, para que tocar una línea no reinstale nada.
COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements.txt

# --- Imagen final ------------------------------------------------------------
FROM python:3.14.6-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Usuario sin privilegios con UID numérico fijo.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin solventa

COPY --from=builder --link /opt/venv /opt/venv
COPY --link src /app/src

WORKDIR /app
USER 10001

# Comprueba que el BUCLE CONSUMIDOR gira, no que un puerto acepte conexiones:
# el worker refresca una clave de latido con TTL en cada vuelta.
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-m", "cotizador.health"]

# Forma exec: el proceso es PID 1 y recibe SIGTERM directamente.
CMD ["python", "-m", "cotizador"]
