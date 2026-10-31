# База данных сервиса

Сервис пока хранит проекты в папках (`service/storage.py`). База заведена рядом: схема,
миграции и слой доступа готовы и проверены, к `Workflow` она ещё не подключена. Ядро
(`floorplan_engine` без `service/`) о базе не знает и не узнает: оно собирает чертёж из папки.

## Запуск локально

```bash
cp .env.example .env                 # пароль и порт локальной базы
docker compose up -d db              # Postgres 17, контейнер floorplan-engine-db, порт 5433
export DATABASE_URL=postgresql+psycopg://floorplan_engine:floorplan_engine@localhost:5433/floorplan_engine
uv run alembic upgrade head          # создать или обновить таблицы
```

Новая миграция после правки `src/floorplan_engine/service/db/models.py`:

```bash
uv run alembic revision --autogenerate -m "что изменилось"
```

Тесты базы (`tests/service/test_db.py`) работают на SQLite в памяти — Docker им не нужен.

## Код

| Модуль | Что в нём |
| --- | --- |
| `service/db/models.py` | Таблицы (SQLAlchemy 2). JSON — `jsonb` в Postgres, текст в SQLite |
| `service/db/session.py` | Подключение: `DATABASE_URL`, `make_engine`, `make_sessions`, `create_tables` (тесты) |
| `service/db/repositories.py` | Проекты, источники (без повторов по sha256), кэш выжимок по версии алгоритма, версии модели, расход LLM. Функции не делают commit — транзакцией управляет вызывающий |
| `migrations/` | Alembic: `env.py`, `versions/0001_initial.py` |

## Схема

Пометка «новое» — что добавила миграция `0002_auth_access.py` (2026-10-28) к `0001_initial.py`.
Таблица сессий в базе — `user_session`.

```mermaid
erDiagram
  APP_USER {
    uuid id PK
    string email UK
    string name "новое"
    string account_type "новое: client | pro"
    bool is_superuser "новое: владелец платформы, видит всё"
    bool is_active "новое: блокировка"
    timestamp last_login_at "новое"
    timestamp created_at
  }
  OAUTH_ACCOUNT {
    uuid id PK "новое"
    uuid user_id FK
    string provider "google | apple | …"
    string provider_user_id "UK с provider"
    string email
    timestamp created_at
  }
  SUPPORT_GRANT {
    uuid id PK "новое: доступ разработчика к проекту"
    uuid project_id FK
    uuid user_id FK "разработчик"
    uuid granted_by FK "владелец студии"
    text reason
    timestamp expires_at
    timestamp revoked_at
  }
  STUDIO {
    uuid id PK
    string name "студия или бригада монтажника"
    string kind "новое: studio | personal (хозяин квартиры)"
    timestamp created_at
  }
  MEMBERSHIP {
    uuid studio_id PK, FK
    uuid user_id PK, FK
    string role "owner | designer | installer"
  }
  PROJECT_MEMBER {
    uuid project_id PK, FK "новое"
    uuid user_id PK, FK
    string role "client | installer"
    uuid invited_by FK
    timestamp created_at
  }
  INVITE {
    uuid id PK "новое"
    string email
    uuid studio_id FK "или"
    uuid project_id FK "или"
    string role
    string token_hash UK
    uuid invited_by FK
    timestamp expires_at
    timestamp accepted_at
  }
  USER_SESSION {
    uuid id PK "новое"
    uuid user_id FK
    string token_hash UK
    string user_agent
    timestamp created_at
    timestamp last_seen_at
    timestamp expires_at
  }
  STUDIO_PROFILE {
    uuid studio_id PK, FK
    text organization
    string stage
    json signatures
  }
  SYMBOL {
    uuid id PK
    uuid studio_id FK
    string point_type
    text object_key
  }
  PROJECT {
    uuid id PK
    uuid studio_id FK
    string name
    string slug UK "новое: папка projects/<slug> в просмотре"
    string state "created … built"
    text message
    int round
    timestamp created_at
    timestamp updated_at
  }
  SOURCE {
    uuid id PK
    uuid project_id FK
    text file_name
    string sha256 "UK с project_id"
    string kind
    int pages
    text object_key
  }
  FACTS_PAGE {
    uuid id PK
    uuid source_id FK
    int page
    string algo_version
    float scale_mm
    float confidence
    json facts
  }
  MODEL_VERSION {
    uuid id PK
    uuid project_id FK
    int version "UK с project_id"
    text room_yaml
    text electrical_yaml
    text intake_yaml
    text answers_yaml
    text wiring_yaml "новое: правки трасс"
    string author "analyzer | user | operator"
    uuid user_id FK "новое: кто именно"
    timestamp created_at
  }
  ROUND {
    uuid id PK
    uuid project_id FK
    int number
    uuid model_version_id FK
  }
  QUESTION {
    uuid id PK
    uuid round_id FK
    string qid
    string stage
    text target
    string severity
    text text
    string state
  }
  ANSWER {
    uuid question_id PK, FK
    json value
    uuid user_id FK
    timestamp created_at
  }
  BUILD {
    uuid id PK
    uuid model_version_id FK
    string status
    json report
    timestamp created_at
  }
  BUILD_FILE {
    uuid id PK
    uuid build_id FK
    string kind "dxf | epd | pdf | xlsx | csv | png"
    text name
    text object_key
  }
  PRICE_LIST {
    uuid id PK "новое: свой id"
    uuid studio_id FK "общий прайс студии — или"
    uuid project_id FK "прайс проекта"
    string currency
    string date
    json items
    json board_kit
  }
  USAGE {
    uuid id PK
    uuid project_id FK
    int round
    string backend
    string model
    int input_tokens
    int output_tokens
    numeric cost_usd
  }
  AUDIT_EVENT {
    uuid id PK "новое"
    uuid project_id FK
    uuid user_id FK
    string action "login | answer | wiring_edit | build | invite | download | support_access"
    json payload
    timestamp created_at
  }

  APP_USER ||--o{ MEMBERSHIP : "в студиях"
  STUDIO ||--o{ MEMBERSHIP : "сотрудники"
  APP_USER ||--o{ PROJECT_MEMBER : "доступ к проектам"
  PROJECT ||--o{ PROJECT_MEMBER : "клиент, монтажник"
  APP_USER ||--o{ USER_SESSION : "сессии"
  APP_USER ||--o{ OAUTH_ACCOUNT : "вход через Google и др."
  APP_USER ||--o{ SUPPORT_GRANT : "доступ для поддержки"
  PROJECT ||--o{ SUPPORT_GRANT : "кому открыт"
  STUDIO ||--o{ INVITE : "приглашения в студию"
  PROJECT ||--o{ INVITE : "приглашения в проект"
  STUDIO ||--o| STUDIO_PROFILE : "штамп"
  STUDIO ||--o{ SYMBOL : "библиотека УГО"
  STUDIO ||--o{ PROJECT : "проекты"
  STUDIO ||--o| PRICE_LIST : "общий прайс"
  PROJECT ||--o| PRICE_LIST : "свой прайс"
  PROJECT ||--o{ SOURCE : "источники"
  SOURCE ||--o{ FACTS_PAGE : "выжимка по страницам"
  PROJECT ||--o{ MODEL_VERSION : "версии YAML"
  PROJECT ||--o{ ROUND : "раунды"
  ROUND ||--o{ QUESTION : "вопросы"
  QUESTION ||--o| ANSWER : "ответ"
  MODEL_VERSION ||--o{ BUILD : "сборки"
  BUILD ||--o{ BUILD_FILE : "файлы сборки"
  PROJECT ||--o{ USAGE : "расход LLM"
  PROJECT ||--o{ AUDIT_EVENT : "журнал"
  APP_USER ||--o{ AUDIT_EVENT : "кто"
```

### Доступ (решения пользователя 2026-10-28, схема — черновик)

| Кто | Как задан | Видит | Может |
| --- | --- | --- | --- |
| Суперпользователь (владелец платформы) | `app_user.is_superuser` | все проекты | всё; выдаёт студии |
| Владелец, проектировщик студии | `membership` (`owner`, `designer`) | все проекты своей студии | загрузка, вопросы, правка трасс, приглашения, доступ поддержке |
| Монтажник студии | `membership` (`installer`) | все проекты своей студии | смотреть, скачать, править трассы |
| Монтажник со стороны | `project_member` (`installer`) | только проекты, куда позвали | смотреть, скачать, править трассы |
| Клиент (хозяин квартиры) | `account_type = client` + `project_member` (`client`) | **один** свой проект целиком: чертежи, смета с ценами, вопросы | смотреть, скачать, отвечать на вопросы |
| Разработчик (человек или агент) | обычный пользователь своей тестовой студии | свои тестовые проекты; чужой — только по `support_grant` | чинить баги на тестовых проектах |

- **Два типа учётной записи** (`app_user.account_type`):
  - `client` — хозяин квартиры, где ремонт. Один проект; попадает в него по приглашению
    студии или монтажника. Видит всё: чертежи, смету с ценами, вопросы (упор на
    прозрачность).
  - `pro` — студия или монтажник. Регистрируется сам; при регистрации создаётся его
    `studio` с ним как `owner`. Проектов сколько угодно; позже может позвать в студию
    сотрудников (`membership`).
  Тип выбирается при регистрации и задаёт стартовый экран: клиенту — его проект, `pro` —
  список проектов студии.
- **Разработчик не видит приватные проекты студий.** Особой роли у него нет: это обычный
  пользователь со своей студией и тестовыми проектами (лучше — на отдельной базе стенда).
  Чужой проект открывается только по `support_grant`: его выдаёт владелец студии на
  конкретный проект, с причиной и сроком (по умолчанию 72 часа); каждое открытие — в журнал
  (`support_access`). Видит всё только суперпользователь.
- **Независимый монтажник или бригада — своя `studio`.** Граница доступа — студия.
- **Пространство и фирма** (решение 2026-10-31): первый вход — выбор «Мой ремонт» (личное
  пространство, `studio.kind = personal`) или «Фирма». Фирма регистрируется отдельным шагом
  (`access.register_firm`, `POST /api/auth/firm`): название, вид (`studio.business`:
  `design` — дизайн и проект, `electric` — электромонтаж, `construction` — ремонт и
  строительство, `master` — частный мастер), город и телефон по желанию. Тип пространства —
  `studio.kind`; `app_user.account_type` — подсказка стартового экрана. Фирма — одна на
  человека: сотрудник чужой фирмы свою не заводит; несколько фирм и переключатель — позже.
  Вид фирмы пока ни на что не влияет — заведён, чтобы потом развести права, листы и тарифы.
- **Клиент — один проект**: частичный уникальный индекс Postgres
  `project_member (user_id) WHERE role = 'client'`.
- **Проверка доступа — одна функция** `access(user, project) → роль | None`:
  суперпользователь → всё; `membership` по `project.studio_id`; `project_member`;
  действующий `support_grant`. Ею фильтруются список проектов и каждый запрос API.

### Вход (решения пользователя 2026-10-28)

- **Без паролей: Google или код на почту.** Apple не делаем ($99 в год), другие
  провайдеры — строкой в `oauth_account`. Новая учётка провайдера с подтверждённым email,
  который уже есть, — тот же пользователь; неподтверждённый email не привязывается.
- **Код на почту** (решение 2026-10-31): email → 6 цифр в письме → вход. Код подтверждает
  почту, поэтому вход по коду — учётка провайдера `email` с подтверждённым адресом: тот же
  email из Google — тот же пользователь. Код живёт 10 минут, действует последний; 5 неверных
  вводов — код сгорает; новый — не чаще раза в минуту и не больше 5 в час на адрес. В базе
  (`email_code`) — только sha256 «email:код». Письма — SMTP (`SMTP_HOST`…, любой сервис:
  Resend, Postmark, SES); без SMTP на http (локально) код пишется в терминал сервера, на
  https вход по коду выключен. Ограничения по IP — пока нет (до выхода к пользователям).
- **Два типа учётки** (`account_type`, выбор при первом входе, не меняется): `client` —
  хозяин квартиры, личное пространство (`studio.kind = personal`) на один проект, может
  загрузить свой план сам и позвать монтажника; `pro` — студия или монтажник, своя студия,
  проектов сколько угодно. Приглашённый без типа получает его по роли приглашения.
- **Сессия** — `user_session`: случайный токен в cookie `shtroba_session` (HttpOnly,
  SameSite=Lax, Secure на https, 30 дней), в базе только sha256. Выход — удаление сессии.
- **Приглашение** (`invite`) — одноразовая ссылка на 7 дней `…/?invite=<токен>`; ключ —
  сама ссылка, email не сверяется (студия видит, кто принял). Хозяин квартиры зовёт в свой
  проект только монтажника.
- **Вход для разработки** (`SHTROBA_DEV_LOGIN=1`, решение 2026-10-31): кнопка «Зайти для
  разработки» — вход без Google и письма под первым адресом `SHTROBA_SUPERUSERS` (полные
  права, не только чтение). Только http (локально): на https или в Railway `production`
  сервис с ним не стартует.
- **Гость отладки** (`SHTROBA_VISITOR=1`): «Войти как гость» без входа — видит все проекты,
  только чтение. В окружении Railway `production` сервис с ним не стартует.
- **Журнал** (`audit_event`): входы, приглашения, проекты, выдача и использование доступа
  поддержки.

### Код входа

| Модуль | Что в нём |
| --- | --- |
| `service/db/access.py` | Правила: роль в проекте (`project_role`), права (`can`), пользователи OAuth, тип учётки, сессии, приглашения, доступ поддержки, журнал |
| `service/db/email_codes.py` | Код на почту: выдать (`issue_code`, частота), проверить (`check_code`, срок, попытки) |
| `service/api/mail.py` | Письмо с кодом на языке страницы: SMTP или лог (локально) |
| `service/api/auth.py` | Веб: настройки из окружения (`AuthConfig.from_env`), Google через Authlib, код на почту (`/api/auth/email/start`, `/verify`), маршруты `/api/auth/*` и `/api/invites/*`, проверка доступа к `/api/projects/{имя}/…` (нет входа — 401, чужой проект — 404, нет права — 403) |
| `web/src/pages/Gate`, `widgets/EmailLogin`, `shared/auth.ts` | Экран входа (Google, код на почту), выбор «кто вы», принятие приглашения, «Выйти» |

Пока проекты живут в папках, строка `project` связана с папкой по `slug`:
`floorplan-engine access link projects/<имя> --owner <email>` (владелец уже входил и выбрал
тип), ссылка-приглашение — `floorplan-engine access invite projects/<имя> --role client`.
Папка без строки в базе видна только суперпользователю и гостю.

Окружение — в `.env.example` и docstring `service/api/auth.py`. Локально — файл `.env` в корне
репозитория: его читают команды сервиса (`view`, `dev`, `serve`, `access`, `analyze`;
`cli.load_env`), заданное в окружении главнее; `build` и `check` его не читают. Скачанный из
консоли `client_secret_*.json` в git не кладётся (`.gitignore`): id и секрет — в `.env`. На Railway: Postgres (адрес
`postgresql://…` код сам переводит на psycopg 3), `SHTROBA_AUTH=on`, `SHTROBA_SECRET`,
`SHTROBA_PUBLIC_URL`, `GOOGLE_CLIENT_ID` и `GOOGLE_CLIENT_SECRET`, `SHTROBA_SUPERUSERS`;
миграции применяет `deploy/start.sh` при старте. В Google Cloud Console у OAuth-клиента
адрес возврата — `<SHTROBA_PUBLIC_URL>/api/auth/google/callback`.

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
6. **Студии и доступ.** Сделано 2026-10-28 для просмотра: вход (Google), роли, проверка
   доступа к каждому запросу. Осталось: профиль студии — из `studio_profile` вместо
   `studio.yaml`; доступ в API сервиса (`app.py`); экраны приглашений и доступа поддержки.
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
