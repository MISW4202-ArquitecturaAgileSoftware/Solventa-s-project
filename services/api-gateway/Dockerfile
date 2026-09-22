# syntax=docker/dockerfile:1
#
# api-gateway autocontenido. El contexto de build es esta misma carpeta.

FROM python:3.14.6-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_COMPILE=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements.txt

FROM python:3.14.6-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin solventa

COPY --from=builder --link /opt/venv /opt/venv
COPY --link src /app/src

WORKDIR /app
USER 10001

# Sin estado propio: no hay volumen que crear. Más hilos que los demás
# servicios porque cada petición retiene uno mientras espera a Autenticación
# y a Validación.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "32", \
     "--worker-class", "gthread", "--timeout", "30", "--access-logfile", "-", \
     "api_gateway.app:crear_app()"]
