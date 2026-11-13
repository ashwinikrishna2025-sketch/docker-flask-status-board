# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: build the dependencies into a virtualenv.
# Build tools and pip caches stay in this stage and never reach the final image.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copied on its own so this layer is cached until the dependencies change.
COPY requirements.txt .
RUN pip install --requirement requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: the runtime image. Carries the virtualenv and the app, nothing else.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# Run as an unprivileged user, not root.
RUN useradd --create-home --shell /usr/sbin/nologin appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY app/ ./app/

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-m", "app.healthcheck"]

# gunicorn, not the Flask development server.
# exec keeps gunicorn as PID 1 so it receives SIGTERM and shuts down cleanly.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 30 --access-logfile - app.main:app"]
