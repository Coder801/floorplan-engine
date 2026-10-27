#!/bin/bash
# Запуск в контейнере. Источник правды — проекты из образа (git): при каждом деплое они
# заменяют копию на volume. С сервера сохраняется только wiring.yaml (правки трасс в
# просмотре); затем проект пересобирается — листы всегда по текущим YAML и трассам.
# Проекты, которых нет в образе, на volume не трогаются.
# Дальше — API просмотра и Caddy; упал любой — контейнер перезапускается.
set -e
mkdir -p "$PROJECTS_DIR"
for seed in /app/projects-seed/*/; do
  name=$(basename "$seed")
  dest="$PROJECTS_DIR/$name"
  kept=""
  if [ -f "$dest/wiring.yaml" ]; then
    kept=$(mktemp)
    cp "$dest/wiring.yaml" "$kept"
  fi
  rm -rf "$dest"
  cp -r "$seed" "$dest"
  [ -n "$kept" ] && mv "$kept" "$dest/wiring.yaml"
  floorplan-engine build "$dest" > /dev/null || echo "Сборка $name не удалась" >&2
done
cp /app/projects-seed/*.yaml "$PROJECTS_DIR"/ 2>/dev/null || true  # профиль студии и т. п.
floorplan-engine view --projects "$PROJECTS_DIR" --host 127.0.0.1 --port 8000 &
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &
wait -n
exit 1
