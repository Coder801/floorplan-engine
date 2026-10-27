---
description: Валидация проекта и превью без перегенерации YAML и DXF
argument-hint: <проект>
allowed-tools: Read, Glob, Bash(uv run floorplan-engine check:*), Bash(uv run floorplan-engine render-artifact:*), Bash(ls:*)
---

Проверь проект `projects/$ARGUMENTS/` — только проверка, ничего не исправляй.

1. `uv run floorplan-engine check projects/$ARGUMENTS`. Перескажи ошибки и предупреждения по-русски
   с путями к полям YAML. При невязке контура покажи ΔX/ΔY и варианты исправления из сообщения
   и спроси, какой размер неверный. Не правь YAML.
   Перескажи статус каждого этапа (готово / есть вопросы / мало данных / данных нет) и открытые
   вопросы из `intake.yaml`, сначала критичные.
2. Если есть `out/project.epd`: `uv run floorplan-engine render-artifact projects/$ARGUMENTS`, затем
   открой `out/artifact/*.png` через Read и проверь:
   - контур замкнут;
   - проёмы на месте;
   - размеры читаются;
   - электрика на своих стенах;
   - подписи не налезают друг на друга.
3. Если YAML новее DXF (сравни через `ls -l`), предупреди, что превью устарело и нужен `build`.
   Сам `build` не запускай.
4. Итог: всё в порядке или список проблем с указанием файла и поля.
