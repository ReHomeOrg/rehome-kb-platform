# reHome KB API gateway — production image (#114).
#
# Multi-stage:
#   1) builder — устанавливает Python deps в виртуальное окружение.
#   2) runtime — minimal image, копируем .venv + код, бежим uvicorn от
#      non-root user'а.
#
# Build: `docker build -t kb-api backend/`
# Run:   `docker run --rm -p 8000:8000 -e DATABASE_URL=... kb-api`

# Base image digest-pinned для supply-chain reproducibility
# (CLAUDE-REVIEWER §"supply-chain reproducibility"). Bump через:
#   docker pull python:3.12-slim-bookworm
#   docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim-bookworm
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:d193c6f51a7dbd10395d6328de3a7edb0516fb0608ca138036576f574c3e07d2

# ============================================================================
# Stage 1: builder
# ============================================================================
FROM ${PYTHON_IMAGE} AS builder

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
FROM ${PYTHON_IMAGE} AS runtime
# Re-declare ARG в stage'е (Docker spec — ARG не наследуется автоматически).
ARG PYTHON_IMAGE

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Safe default: только loopback (sidecar / same-pod reverse-proxy).
    # Override в k8s manifest когда известен ingress CIDR, e.g.
    # FORWARDED_ALLOW_IPS=10.0.0.0/8. WILDCARD "*" — anti-pattern
    # (любой клиент сможет spoof'ить X-Forwarded-For).
    FORWARDED_ALLOW_IPS=127.0.0.1

# Non-root user (uid/gid 1000 совпадает с типичным k8s
# `securityContext.runAsUser: 1000` — coordinate'те значения через
# deploy manifests). Best-practice — процесс не имеет root-прав.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash --create-home app

WORKDIR /app

# Copy installed venv from builder. `--chown` чтобы app user мог читать.
COPY --from=builder --chown=app:app /opt/venv /opt/venv

# Copy source + migrations. NB: миграции в image, но `CMD` их НЕ запускает —
# operator должен выполнить `alembic upgrade head` в init-container'е
# (k8s) или отдельно перед startup (docker-compose).
COPY --chown=app:app src ./src
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./alembic.ini

USER app

# 8000 — internal port; k8s Service port'у может отличаться (ClusterIP).
EXPOSE 8000

# Healthcheck через `/api/v1/health` (liveness — pure-process). Period
# 30s — баланс между detection-speed и нагрузкой; timeout 3s strict.
# Используем `python -c` через urllib (no curl dep — экономит ~10 MB
# apt-cache + одно meaningful CVE-surface package).
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=2).status==200 else 1)" || exit 1

# `--proxy-headers` обязателен за reverse-proxy (k8s ingress, nginx) —
# uvicorn уважает X-Forwarded-* для client IP / scheme detection.
# Shell form для env-expansion FORWARDED_ALLOW_IPS; `exec` replace'ит sh
# своим uvicorn'ом → uvicorn становится PID 1 (signal handling сохраняется).
CMD exec uvicorn src.api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips "$FORWARDED_ALLOW_IPS"
