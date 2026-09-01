# syntax=docker/dockerfile:1
#
# API Gateway. El contexto de build es la RAÍZ del repositorio: la imagen
# necesita libs/solventa-common.

FROM python:3.14.6-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_COMPILE=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY services/api-gateway/requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements.txt

COPY libs/solventa-common /tmp/solventa-common
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install /tmp/solventa-common

FROM python:3.14.6-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin solventa

COPY --from=builder --link /opt/venv /opt/venv
COPY --link services/api-gateway/src /app/src

WORKDIR /app
USER 10001

HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=2).status==200 else 1)"]

# Un worker: el contador del limitador de tasa vive en memoria del proceso y con
# varios workers el límite efectivo se multiplicaría por el número de workers.
# Los hilos bastan: cada petición espera a Votación, que es E/S.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "32", \
     "--worker-class", "gthread", "--timeout", "30", "--access-logfile", "-", \
     "api_gateway.wsgi:app"]
