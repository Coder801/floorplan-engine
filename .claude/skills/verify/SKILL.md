---
name: verify
description: Полная проверка изменений Штробы без LLM и без просмотра картинок — тесты, типы, линтер, регрессия выжимки PDF и раскладки листов кодом. Используй перед тем, как сообщить, что правка готова.
---

# Проверка изменений

1. Код:
   ```bash
   uv run pytest -q && uv run mypy && uv run ruff check . && uv run ruff format --check .
   ```
   Если менялся фронт (`web/`): типы, тесты и сборка (в `web/dist`):
   ```bash
   cd web && npm run check && npm test && npm run build
   ```
2. Если менялся разбор источников (`service/facts/`): выжимка Markdown по векторным PDF
   должна совпасть с эталоном до правки (сохрани эталон в scratchpad до изменений):
   ```bash
   for f in projects/*/source/*.pdf; do uv run shtroba pdf-facts "$f"; done > after.md
   diff before.md after.md
   ```
3. Если менялись листы (`sheets.py`, таблицы, легенда, штамп): собери проекты и проверь
   раскладку кодом — формат, масштаб, ничего не вылезло и не легло на план:
   ```bash
   uv run shtroba build projects/<имя>
   uv run python scripts/check_layout.py <имя> [<имя>…]
   ```
   Картинки листов (`render-artifact`) открывай, только если пользователь просит или кодом
   проблему не найти — это дорого.
4. Сообщи результат: что проверено, что совпало, что нет. Не пиши «готово», если шаг
   пропущен.
