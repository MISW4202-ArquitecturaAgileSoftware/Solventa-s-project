# syntax=docker/dockerfile:1
#
# GestorErrores autocontenido. El contexto de build es esta misma carpeta.

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

# El volumen se monta aquí; el directorio debe existir y pertenecer al usuario
# sin privilegios antes de que Docker lo monte.
RUN mkdir -p /datos && chown 10001:10001 /datos

WORKDIR /app
USER 10001

HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=2).status==200 else 1)"]

# Un solo worker: los contadores y la cola del escritor viven en el proceso, y
# con varios workers /v1/metricas devolvería el estado de uno cualquiera.
# Los hilos bastan: el trabajo es E/S, no CPU.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", \
     "--worker-class", "gthread", "--access-logfile", "-", \
     "gestion_errores.wsgi:app"]
