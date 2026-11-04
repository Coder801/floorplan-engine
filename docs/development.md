# Общие правила разработки

Для всех, кто правит код Штробы, — людей и агентов (`backend-developer`, `frontend-developer`,
`refactor`, `tester`, `ui-designer`). Своё у каждой стороны — в описании агента:
бэк — `.claude/agents/backend-developer.md`, фронт — `.claude/agents/frontend-developer.md`.

## Перед работой

- Прочитай `CLAUDE.md` (правила проекта и модули) и `docs/architecture.md` (кто что считает:
  код или LLM, и в какой функции). Фронт — ещё `web/README.md` (устройство и стили).
- Найди место правки и соседний код. Пиши в его стиле: те же имена, та же плотность
  комментариев, комментарии и сообщения пользователю — по-русски.

## CI

`.github/workflows/ci.yml` на каждый push в ветку: `ruff`, `mypy`, `lint-imports`, `pytest` с
Postgres (`TEST_REQUIRE_DB=1`), типы, тесты и сборка `web/` и `admin/`. Это те же проверки, что
скилл `verify`, кроме выжимки PDF и раскладки листов. Деплой ждёт CI, только если на Railway
включён Wait for CI (настройка сервиса, в репозитории её нет).

## Границы

- Данные пользователя не правишь: `projects/*/room.yaml`, `electrical.yaml`, `intake.yaml`,
  `answers.yaml`, `wiring.yaml` и `source/`. Собирать проекты (`build`) можно — `out/` пишет код.
- `analyze` не запускаешь — тратит токены.
- Ядро (`src/floorplan_engine/`, кроме `service/`) — без LLM, сети и базы; фронт ходит только
  в API (`service/api/viewer.py`), формат страниц — `docs/epd-format.md`. Меняешь смысл ключей
  `.epd` — повышай `FORMAT_VERSION` в `epd/artifact.py` и `web/src/shared/version.ts`; новый
  необязательный ключ версию не меняет.
- Числа и размеры не подгоняешь. Правила перевода источников в YAML — в
  `service/analysis/analyzer_prompt.md`, в `CLAUDE.md` — только порядок работы.
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

## Ветки и релизы

Решение 2026-11-03: `develop` — разработка, `feature/<имя>` — работа, `main` — только релизы с
тегами; релизных веток нет. Версия поднимается при релизе, не при каждом коммите. Ветками
управляет `scripts/flow.py`, пуш всегда руками.

- **Новая работа:** на `develop` → `uv run python scripts/flow.py feature <имя>` — ветка
  `feature/<имя>`, незакоммиченные правки переезжают в неё. `/commit` делает это сам, если
  ты стоишь на `develop` с правками.
- **В develop:** `uv run python scripts/flow.py integrate` — rebase на `develop`, fast-forward,
  ветка удаляется (`--keep` — оставить). История `develop` линейная. Конфликт при rebase
  скрипт не решает: `git rebase --continue` или `--abort`, потом снова `integrate`.
  Пуш: `git push origin develop`.
- **Релиз** (`/release`): на чистом `develop` → `uv run python scripts/flow.py release`
  (сначала `--dry-run`): `main` fast-forward до `develop`, `cz bump` на `main`, `develop`
  fast-forward до `main`. В `main` коммитов мимо `develop` быть не должно — скрипт откажет,
  пока не сделан `git merge main` в `develop`. Пуш: `git push origin main develop --follow-tags`.

- **Всё одной командой** (после `/commit`, из своего терминала — пуш идёт по вашим ключам):
  `uv run python scripts/flow.py ship --increment patch --rebuild` — `feature` → `develop`
  (забытый чистый worktree с `develop` убирается сам), проверки, релиз, вопрос «выпустить и
  запушить?», пуш, ожидание выкладки, пересборка проектов на сервере. `--dry-run` — только план,
  `--yes` — без вопроса.
- **Сервер** (`scripts/server.py`, нужен `railway` с привязанным проектом): `check` — версия,
  число файлов в хранилище, диск (должен быть том, а не `overlay`) и переменные без значений; `rebuild [имена…] [--wait]` — пересобрать проекты текущим
  кодом; `send <проект> room.yaml` — файл модели новой версией, сначала показывает разницу с
  базой. Команды идут внутри контейнера: файлы сборок лежат на его volume, `project push` с
  ноутбука оставил бы их на ноутбуке.

- **Заголовок коммита — Conventional Commits:** `feat(viewer): zoom in on double click`,
  `fix(electrical): …`, `docs: …`, `chore(projects): rebuild out/`. Типы и области — в
  `.claude/agents/committer.md`. Проверяет хук `commit-msg` (husky из `web/`, файл
  `web/.husky/commit-msg` → `uv run cz check`); хук ставится при `npm install` в `web/`
  (`prepare`). Коммит с другим заголовком не проходит.
- **Версия:** `cz bump` внутри `flow.py release`; `--increment patch` задаёт шаг вместо подсчёта по коммитам. Commitizen (`pyproject.toml`,
  `[tool.commitizen]`) считает новую версию по коммитам с прошлого тега (`feat` — minor,
  `fix` — patch; пока версия 0.x, breaking — тоже minor), правит `pyproject.toml`,
  `src/floorplan_engine/__init__.py`, `package.json` и `package-lock.json` в `web/` и
  `admin/`, `uv.lock` (lock-файлы — `scripts/release_lock.py`), дописывает `CHANGELOG.md`, коммитит
  `bump: version …` и ставит тег `vX.Y.Z`. Версия видна в настройках просмотра
  (`web/src/shared/version.ts`), совпадение всех файлов проверяет `tests/test_version.py`.
