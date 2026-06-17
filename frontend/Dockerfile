# reHome KB frontend — production image (#123).
#
# Three-stage build:
#   1) deps    — npm ci с production+dev deps (нужны build-time).
#   2) builder — `next build` → .next/standalone (self-contained server).
#   3) runtime — minimal node + только standalone output.
#
# Полагается на `output: "standalone"` в next.config.mjs.
#
# Build: `docker build -t kb-frontend frontend/`
# Run:   `docker run --rm -p 3000:3000 kb-frontend`

# Base image digest-pinned для supply-chain reproducibility (CLAUDE.md).
# Bump через:
#   docker pull node:20-bookworm-slim
#   docker inspect --format='{{index .RepoDigests 0}}' node:20-bookworm-slim
ARG NODE_IMAGE=node:20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0

# ============================================================================
# Stage 1: deps — install npm packages with layer cache
# ============================================================================
FROM ${NODE_IMAGE} AS deps

WORKDIR /app

# package*.json copy'ятся первыми — Docker layer cache не invalidate'ится
# на code changes пока deps не менялись.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ============================================================================
# Stage 2: builder — `next build`
# ============================================================================
FROM ${NODE_IMAGE} AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules

# Explicit COPY (не `COPY . .`) — defence-in-depth для ФЗ-152: даже если
# `.dockerignore` regress'ит, stray `.env.production` в repo root не
# попадёт в layer. Список — это всё что `next build` realistically
# нуждается. Vitest config / tests НЕ копируем — prod build их игнорирует.
COPY package.json package-lock.json next.config.mjs \
     tsconfig.json tailwind.config.ts postcss.config.mjs ./
COPY app ./app
COPY lib ./lib

# basePath приложения (см. lib/base-path.ts). Дефолт "/help" (Selectel);
# для поддомен-деплоя собирать с `--build-arg NEXT_PUBLIC_BASE_PATH=`.
# NEXT_PUBLIC_* инлайнится в бандл во время `next build`.
ARG NEXT_PUBLIC_BASE_PATH=/help
ENV NEXT_PUBLIC_BASE_PATH=${NEXT_PUBLIC_BASE_PATH}

# Next.js telemetry — отключаем (privacy + slight perf).
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ============================================================================
# Stage 3: runtime — minimal image
# ============================================================================
FROM ${NODE_IMAGE} AS runtime

# Re-declare (ARG не пересекает stage-границы) — нужен для healthcheck-пути.
ARG NEXT_PUBLIC_BASE_PATH=/help
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    NEXT_PUBLIC_BASE_PATH=${NEXT_PUBLIC_BASE_PATH}

# `node:bookworm-slim` ships with user `node` (uid 1000) ready-to-use —
# не создаём дубликат. uid 1000 совпадает с k8s securityContext.runAsUser:1000.
# NB asymmetry с backend Dockerfile (#114): backend создаёт `app` user
# (uid 1000) явно — там slim base ships БЕЗ pre-built non-root user. В
# обоих случаях `id -u` в контейнере = 1000, deploy manifests могут не
# различать.

WORKDIR /app

# Copy standalone output: `.next/standalone/` это самодостаточный сервер
# (server.js + минимальные node_modules), `.next/static/` — статические
# build artifacts. `public/` dir не существует в этом проекте — favicon и
# global-error.tsx живут в `app/`. Если в future появится public/, добавить
# `COPY --from=builder --chown=node:node /app/public ./public`.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node

EXPOSE 3000

# Healthcheck через main page — Next.js по умолчанию отвечает 200 на `/`
# когда app routing работает. `node:slim` имеет node, не имеет curl —
# inline HTTP check через node http module.
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD node -e "const b=process.env.NEXT_PUBLIC_BASE_PATH ?? '/help'; require('http').get('http://127.0.0.1:3000'+(b||'/'), r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))" || exit 1

# Next.js standalone server entry point.
CMD ["node", "server.js"]
