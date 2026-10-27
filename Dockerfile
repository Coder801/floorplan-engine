# Просмотр проектов для Railway: фронт web/dist (Caddy) + API `floorplan-engine view`.
# Caddy слушает $PORT, отдаёт статику и проксирует /api на view (127.0.0.1:8000).

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM caddy:2.8.4 AS caddy

FROM python:3.12-slim
# libglib — для opencv-headless из группы service; DejaVu — запасной шрифт ezdxf для стилей
# DXF, кроме IBM Plex (в slim-образе шрифтов нет: «no fonts available» при сборке листов)
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

COPY --from=web /web/dist /srv/web
# Проекты в образе — начальные; рабочая папка — volume PROJECTS_DIR (правки wiring.yaml)
COPY projects/ /app/projects-seed/
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY deploy/start.sh /app/start.sh

ENV PROJECTS_DIR=/data/projects PORT=8080
CMD ["/app/start.sh"]
