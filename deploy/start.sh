#!/bin/bash
# Запуск в контейнере. Источник правды — проекты из образа (git): при каждом деплое они
# заменяют копию на volume. С сервера сохраняются только wiring.yaml (правки трасс) и
# variant.yaml (выбранный вариант проводки) из просмотра; затем проект пересобирается.
# Проекты, которых нет в образе, на volume не трогаются.
# Дальше — API просмотра и Caddy; упал любой — контейнер перезапускается.
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
cp /app/projects-seed/*.yaml "$PROJECTS_DIR"/ 2>/dev/null || true  # профиль студии и т. п.
# Вход включён (SHTROBA_AUTH=on) — сначала миграции базы (DATABASE_URL). Папки проектов
# с владельцем связывает сам сервис при его входе (SHTROBA_OWNER, service/api/auth.py)
if [ "$SHTROBA_AUTH" = "on" ]; then
  (cd /app && alembic upgrade head)
fi
floorplan-engine view --projects "$PROJECTS_DIR" --host 127.0.0.1 --port 8000 &
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &
wait -n
exit 1
