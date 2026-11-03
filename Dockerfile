# Project viewer for Railway: the web/dist frontend and the admin/dist platform admin (Caddy) + the
# `floorplan-engine view` API.
# Caddy listens on $PORT, serves static files and proxies /api to view (127.0.0.1:8000).

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Platform admin (admin/): its own front, served at /admin/ on the same domain (shared login cookie)
FROM node:22-slim AS admin
WORKDIR /admin
COPY admin/package.json admin/package-lock.json ./
RUN npm ci
COPY admin/ ./
RUN npm run build

FROM caddy:2.8.4 AS caddy

FROM python:3.12-slim
# libglib is for opencv-headless from the service group; DejaVu is the ezdxf fallback font for
# DXF styles other than IBM Plex (the slim image has no fonts: "no fonts available" when building sheets)
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1 PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
RUN uv sync --frozen --no-dev
# Database migrations run on start when login is on (deploy/start.sh)
COPY alembic.ini ./
COPY migrations/ migrations/

COPY --from=web /web/dist /srv/web
COPY --from=admin /admin/dist /srv/admin/admin
# Projects in the image are the seed; the working folder is the PROJECTS_DIR volume (wiring.yaml edits)
COPY projects/ /app/projects-seed/
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY deploy/start.sh /app/start.sh

ENV PROJECTS_DIR=/data/projects PORT=8080
CMD ["/app/start.sh"]
