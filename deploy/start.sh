#!/bin/bash
# Container start. Then the viewer API and Caddy start; if either dies, the container restarts.
#
# With login on (SHTROBA_AUTH=on) projects live in the database (decision 2026-11-03, docs/
# database.md, "Переезд проектов из папок в базу"; SHTROBA_STORAGE=files turns it back): files go
# to SHTROBA_OBJECTS on the volume. The projects in the image (git) are only a seed: on start
# they are moved into the owner's studio (SHTROBA_OWNER; the owner and the firm are created if
# missing) once — projects and the studio price list already in the database are not touched,
# the database is the truth.
#
# Without login — the old folder mode: the projects in the image replace their copy on the
# volume, keeping only wiring.yaml and variant.yaml written by the viewer, then are rebuilt.
set -e
mkdir -p "$PROJECTS_DIR"
# The market sample (market.yaml) is shared and always comes from git
cp /app/projects-seed/market.yaml "$PROJECTS_DIR"/ 2>/dev/null || true

STORAGE="${SHTROBA_STORAGE:-}"
if [ "$SHTROBA_AUTH" = "on" ] && [ "$STORAGE" != "files" ]; then
  STORAGE=db
fi
export SHTROBA_STORAGE="$STORAGE"
export SHTROBA_OBJECTS="${SHTROBA_OBJECTS:-/data/objects}"

if [ "$SHTROBA_AUTH" = "on" ]; then
  (cd /app && alembic upgrade head)
fi

if [ "$STORAGE" = "db" ]; then
  mkdir -p "$SHTROBA_OBJECTS"
  # Without a volume the files live in the container and the next deploy deletes them
  mountpoint -q /data || echo "ВНИМАНИЕ: /data — не volume, файлы проектов пропадут при выкладке" >&2
  if [ -n "$SHTROBA_OWNER" ]; then
    floorplan-engine project import /app/projects-seed --owner "$SHTROBA_OWNER" \
      --create-owner --only-new || echo "Перенос проектов из образа в базу не удался" >&2
  else
    echo "SHTROBA_OWNER не задан: проекты из образа в базу не переносятся" >&2
  fi
else
  for seed in /app/projects-seed/*/; do
    name=$(basename "$seed")
    dest="$PROJECTS_DIR/$name"
    kept=$(mktemp -d)
    for f in wiring.yaml variant.yaml; do
      [ -f "$dest/$f" ] && cp "$dest/$f" "$kept/$f"
    done
    rm -rf "$dest"
    cp -r "$seed" "$dest"
    cp "$kept"/*.yaml "$dest"/ 2>/dev/null || true
    rm -rf "$kept"
    floorplan-engine build "$dest" > /dev/null || echo "Сборка $name не удалась" >&2
  done
  # The studio price list and profile are edited on the server (studio settings), so git only
  # seeds them when the server has none
  for f in prices.yaml studio.yaml; do
    [ -f "/app/projects-seed/$f" ] && [ ! -f "$PROJECTS_DIR/$f" ] && cp "/app/projects-seed/$f" "$PROJECTS_DIR/$f"
  done
fi

floorplan-engine view --projects "$PROJECTS_DIR" --host 127.0.0.1 --port 8000 &
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &
wait -n
exit 1
