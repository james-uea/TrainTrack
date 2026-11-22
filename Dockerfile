# The web front end, built to static files
FROM node:26-slim AS web
WORKDIR /web
RUN npm install -g pnpm@12.21.0
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web ./
RUN pnpm exec vite build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY sql ./sql
COPY src ./src
COPY --from=web /web/dist ./web/dist

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
