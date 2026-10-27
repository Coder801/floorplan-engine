# База данных сервиса

Сервис пока хранит проекты в папках (`service/storage.py`). База заведена рядом: схема,
миграции и слой доступа готовы и проверены, к `Workflow` она ещё не подключена. Ядро
(`shtroba` без `service/`) о базе не знает и не узнает: оно собирает чертёж из папки.

## Запуск локально

```bash
cp .env.example .env                 # пароль и порт локальной базы
docker compose up -d db              # Postgres 17, контейнер shtroba-db, порт 5433
export DATABASE_URL=postgresql+psycopg://shtroba:shtroba@localhost:5433/shtroba
uv run alembic upgrade head          # создать или обновить таблицы
```

Новая миграция после правки `src/shtroba/service/db/models.py`:

```bash
uv run alembic revision --autogenerate -m "что изменилось"
```

Тесты базы (`tests/test_db.py`) работают на SQLite в памяти — Docker им не нужен.

## Код

| Модуль | Что в нём |
| --- | --- |
| `service/db/models.py` | Таблицы (SQLAlchemy 2). JSON — `jsonb` в Postgres, текст в SQLite |
| `service/db/session.py` | Подключение: `DATABASE_URL`, `make_engine`, `make_sessions`, `create_tables` (тесты) |
| `service/db/repositories.py` | Проекты, источники (без повторов по sha256), кэш выжимок по версии алгоритма, версии модели, расход LLM. Функции не делают commit — транзакцией управляет вызывающий |
| `migrations/` | Alembic: `env.py`, `versions/0001_initial.py` |

## Схема

```mermaid
erDiagram
  STUDIO ||--o{ MEMBERSHIP : "сотрудники"
  APP_USER ||--o{ MEMBERSHIP : "роли"
  STUDIO ||--o| STUDIO_PROFILE : "штамп"
  STUDIO ||--o{ PROJECT : "проекты"
  STUDIO ||--o{ SYMBOL : "библиотека УГО"
  PROJECT ||--o{ SOURCE : "источники"
  SOURCE ||--o{ FACTS_PAGE : "выжимка по страницам"
  PROJECT ||--o{ MODEL_VERSION : "версии YAML"
  PROJECT ||--o{ ROUND : "раунды"
  ROUND ||--o{ QUESTION : "вопросы"
  QUESTION ||--o| ANSWER : "ответ"
  MODEL_VERSION ||--o{ BUILD : "сборки"
  BUILD ||--o{ BUILD_FILE : "файлы сборки"
  PROJECT ||--o| PRICE_LIST : "прайс"
  PROJECT ||--o{ USAGE : "расход LLM"
```

Что из папки проекта куда переходит:

| Сейчас (файлы) | В базе | Сам файл |
| --- | --- | --- |
| `service.json` | `project` (состояние, раунд, сообщение) | — |
| `projects/studio.yaml` | `studio`, `studio_profile` | — |
| `source/*` | `source` (имя, sha256, тип, страниц) | объектное хранилище, `object_key` |
| выжимка `pdf-facts` / `facts` | `facts_page`: JSON (`facts.analysis.to_dict`) + сводка колонками | — |
| `room.yaml`, `electrical.yaml`, `intake.yaml`, `answers.yaml` | `model_version` (тексты, автор, номер) | — |
| `rounds/NNN/` | `round`, `question`, `answer` | — |
| `out/report.json` | `build.report` | — |
| `out/project.dxf`, `project.epd`, `estimate.*`, `*.csv` | `build_file` (вид, имя, ключ) | объектное хранилище |
| `prices.yaml` | `price_list` | — |
| `usage.jsonl` | `usage` | — |

## Что нужно, чтобы полностью переехать на серверы и удалить локальные файлы

Порядок работ; пока все пункты не сделаны, папки остаются источником правды.

1. **Объектное хранилище.** Интерфейс `ObjectStore` (`put`, `get`, `delete`, подписанная
   ссылка на скачивание) и две реализации: локальная папка (разработка) и S3-совместимое
   хранилище (R2 или S3). Для разработки — отдельный файловый сервер, чтобы картинки и
   файлы отдавались без прогона трафика через API (решение 2026-10-23: позже).
2. **`DbStorage` за интерфейсом `Storage`.** Те же методы, что у файловой реализации
   (`create`, `load`, `save`, `list`, `delete`, `write_model`, `save_round`, `lock`), на
   репозиториях `service/db/repositories.py`. Блокировка проекта — `SELECT … FOR UPDATE`
   или advisory lock Postgres вместо `threading.Lock` (сервисов может быть несколько).
3. **Рабочая папка на время операции.** Ядро собирает из папки: перед анализом и сборкой
   `DbStorage` выкладывает во временную папку последнюю `model_version` и источники из
   хранилища, после — забирает `out/` (в `build`, `build_file` и хранилище) и новые YAML
   анализатора (в новую `model_version`), папку удаляет. `pipeline` не меняется.
4. **Кэш выжимок.** `facts_text` анализатора и порог `facts/gate.py` сначала смотрят
   `cached_facts` по источнику, считают только то, чего нет (`save_facts`).
5. **Расход LLM** — в `usage` вместо `usage.jsonl`; `ProjectInfo.llm_*` — суммой из базы.
6. **Студии и доступ.** Вход пользователя, `membership` с ролями, фильтр всех запросов
   API по студии проекта; профиль студии — из `studio_profile` вместо `studio.yaml`.
7. **Перенос существующих проектов.** Команда импорта: папка `data/projects/<id>/` (и
   `projects/<имя>/` оператора) → строки базы и файлы в хранилище; обратная выгрузка
   проекта в папку — для режима оператора в Claude Code.
8. **Переключение.** Флаг выбора хранилища (`--storage files|db`), прогон полного цикла
   сервиса на базе (тесты `test_service.py` — на обеих реализациях), затем `db` по
   умолчанию.
9. **Удаление локальных файлов.** Только после переноса и сверки: число проектов, файлов и
   хешей в хранилище совпадает с папками. Тогда `data/projects/` удаляется, `FileStorage`
   остаётся для разработки и тестов.
10. **Эксплуатация.** Резервные копии Postgres и хранилища, миграции Alembic при выкладке,
    секреты (`DATABASE_URL`, ключи хранилища) — из окружения сервера, не из `.env`.
