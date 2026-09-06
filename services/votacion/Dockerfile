# syntax=docker/dockerfile:1
#
# Votación autocontenido. El contexto de build es esta misma carpeta.

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

# Un worker y muchos hilos: cada petición pasa la mayor parte de su vida
# bloqueada en BLPOP, que es espera de E/S, no CPU.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "32", \
     "--worker-class", "gthread", "--timeout", "30", "--access-logfile", "-", \
     "votacion.app:crear_app()"]
