# reHome KB API gateway — production image (#114).
#
# Multi-stage:
#   1) builder — устанавливает Python deps в виртуальное окружение.
#   2) runtime — minimal image, копируем .venv + код, бежим uvicorn от
#      non-root user'а.
#
# Build: `docker build -t kb-api backend/`
# Run:   `docker run --rm -p 8000:8000 -e DATABASE_URL=... kb-api`

# ============================================================================
# Stage 1: builder
# ============================================================================
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Сначала только requirements — leverage Docker layer cache: если код
# изменился, но deps не — pip install пропускается.
COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ============================================================================
# Stage 2: runtime
# ============================================================================
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# `curl` нужен для HEALTHCHECK; больше системных зависимостей runtime
# не требует (psycopg2 не используется — asyncpg чисто Python).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (uid/gid 1000). Best-practice безопасности — процесс
# не имеет root-прав в контейнере.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash --create-home app

WORKDIR /app

# Copy installed venv from builder. `--chown` чтобы app user мог читать.
COPY --from=builder --chown=app:app /opt/venv /opt/venv

# Copy source + migrations (alembic runs at startup или separately).
COPY --chown=app:app src ./src
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./alembic.ini

USER app

EXPOSE 8000

# Healthcheck через `/api/v1/health` (liveness — pure-process). Period
# 30s — баланс между detection-speed и нагрузкой; timeout 3s strict.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

# `--proxy-headers` обязателен за reverse-proxy (k8s ingress, nginx) —
# uvicorn будет уважать X-Forwarded-* для client IP / scheme detection.
CMD ["uvicorn", "src.api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
