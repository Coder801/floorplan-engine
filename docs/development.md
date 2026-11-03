# Общие правила разработки

Для всех, кто правит код Штробы, — людей и агентов (`backend-developer`, `frontend-developer`,
`refactor`, `tester`, `ui-designer`). Своё у каждой стороны — в описании агента:
бэк — `.claude/agents/backend-developer.md`, фронт — `.claude/agents/frontend-developer.md`.

## Перед работой

- Прочитай `CLAUDE.md` (правила проекта и модули) и `docs/architecture.md` (кто что считает:
  код или LLM, и в какой функции). Фронт — ещё `web/README.md` (устройство и стили).
- Найди место правки и соседний код. Пиши в его стиле: те же имена, та же плотность
  комментариев, комментарии и сообщения пользователю — по-русски.

## Границы

- Данные пользователя не правишь: `projects/*/room.yaml`, `electrical.yaml`, `intake.yaml`,
  `answers.yaml`, `wiring.yaml` и `source/`. Собирать проекты (`build`) можно — `out/` пишет код.
- `analyze` не запускаешь — тратит токены.
- Ядро (`src/floorplan_engine/`, кроме `service/`) — без LLM, сети и базы; фронт ходит только
  в API (`service/api/viewer.py`), формат страниц — `docs/epd-format.md`. Меняешь смысл ключей
  `.epd` — повышай `FORMAT_VERSION` в `epd/artifact.py` и `web/src/shared/version.ts`; новый
  необязательный ключ версию не меняет.
- Числа и размеры не подгоняешь. Правила перевода источников в YAML живут в двух местах —
  `CLAUDE.md` и `service/analysis/analyzer_prompt.md`: меняешь в одном — меняй в другом.
- Картинки листов открываешь, только если кодом проблему не найти или пользователь просит.
- Коммитишь, только если пользователь попросил.

## Как работать

1. Новое поведение — с тестом на синтетических данных (бэк — `tests/`, фронт — `*.test.ts`
   рядом с кодом). Багфикс — с тестом, который ловит баг.
2. Типизация везде: `mypy --strict` на бэке, `strict` TypeScript на фронте; без `any` и
   подавлений, если можно обойтись.
3. Документация — в том же изменении: `docs/architecture.md` (если меняется, где что
   считается), `docs/status.md` (строка о сделанном), `CLAUDE.md` (модуль или правило),
   `web/README.md` (устройство фронта), `docs/epd-format.md` (формат страниц).
4. База сервиса — только Postgres, и в тестах тоже: перед тестами `docker compose up -d db`
   (`tests/service/conftest.py`). Новое поле или таблица — миграцией в том же изменении,
   иначе упадёт `test_migrations_match_models`.
5. Перед тем как сообщить, что готово, — скилл `verify`: тесты, типы и линтер обеих сторон,
   которых касалось изменение, и раскладка — контракты импортов бэка (`uv run lint-imports`)
   и `src/structure.test.ts` фронта.
6. В ответе: что сделано, что проверено и чем, что не проверено и почему. Не пиши «готово»,
   если шаг пропущен.

## Коммиты и версии

Решение 2026-11-03: версия поднимается при релизе, не при каждом коммите.

- **Заголовок коммита — Conventional Commits:** `feat(viewer): zoom in on double click`,
  `fix(electrical): …`, `docs: …`, `chore(projects): rebuild out/`. Типы и области — в
  `.claude/agents/committer.md`. Проверяет хук `commit-msg` (husky из `web/`, файл
  `web/.husky/commit-msg` → `uv run cz check`); хук ставится при `npm install` в `web/`
  (`prepare`). Коммит с другим заголовком не проходит.
- **Релиз:** `uv run cz bump` (сначала `--dry-run`). Commitizen (`pyproject.toml`,
  `[tool.commitizen]`) считает новую версию по коммитам с прошлого тега (`feat` — minor,
  `fix` — patch; пока версия 0.x, breaking — тоже minor), правит `pyproject.toml`,
  `src/floorplan_engine/__init__.py`, `web/package.json` и `web/package-lock.json`
  (`scripts/release_lock.py`), дописывает `CHANGELOG.md`, коммитит `bump: version …` и ставит
  тег `vX.Y.Z`. Пуш с тегом — руками: `git push --follow-tags`. Версия видна в настройках
  просмотра (`web/src/shared/version.ts`), совпадение трёх файлов проверяет
  `tests/test_version.py`.
