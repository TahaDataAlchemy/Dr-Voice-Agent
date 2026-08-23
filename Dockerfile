# ---------- stage 1: build the Next.js dashboard (static export) ----------
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- stage 2: FastAPI backend + static dashboard ----------
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/
WORKDIR /app

# Dependencies first (cached layer), then the code.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

COPY config.py main.py alembic.ini ./
COPY core ./core
COPY modules ./modules
COPY alembic ./alembic
COPY scripts ./scripts
COPY --from=frontend /app/frontend/out ./static

EXPOSE 8000
# Migrations run inside the app's lifespan (alembic upgrade head on Postgres).
CMD ["sh", "-c", "uvicorn core.server:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
