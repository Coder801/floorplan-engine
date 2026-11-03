#!/bin/bash
# Container start. The source of truth is the projects in the image (git): every deploy
# replaces the copy on the volume. Only wiring.yaml (route edits) and variant.yaml (the chosen
# wiring variant) from the viewer are kept from the server; then the project is rebuilt.
# Projects that are not in the image are left alone on the volume.
# Then the viewer API and Caddy start; if either dies, the container restarts.
set -e
mkdir -p "$PROJECTS_DIR"
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
cp /app/projects-seed/*.yaml "$PROJECTS_DIR"/ 2>/dev/null || true  # studio profile and the like
# Login is on (SHTROBA_AUTH=on): run database migrations first (DATABASE_URL). The service
# links project folders to the owner itself when they log in (SHTROBA_OWNER, service/api/auth.py)
if [ "$SHTROBA_AUTH" = "on" ]; then
  (cd /app && alembic upgrade head)
fi
floorplan-engine view --projects "$PROJECTS_DIR" --host 127.0.0.1 --port 8000 &
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &
wait -n
exit 1
