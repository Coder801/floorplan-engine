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

Тесты базы (`tests/service/`) идут на тестовом Postgres из `docker compose` (порт 5433, база `*_test`, миграции Alembic — `tests/service/conftest.py`); Postgres не запущен — пропускаются, `TEST_REQUIRE_DB=1` делает пропуск ошибкой.

## Код

| Модуль | Что в нём |
| --- | --- |
| `service/db/models.py` | Таблицы (SQLAlchemy 2). JSON — `jsonb` в Postgres, текст в SQLite |
| `service/db/session.py` | Подключение: `DATABASE_URL`, `make_engine`, `make_sessions`. База — только Postgres (решение 2026-11-01): схему строят миграции, `create_tables` и SQLite убраны |
| `tests/service/conftest.py` | Тесты базы — на Postgres из `docker-compose.yml`, своя база `floorplan_engine_test` (`TEST_DATABASE_URL`, имя обязано кончаться на `_test` — она пересоздаётся): миграции вверх, вниз до нуля и снова вверх, после теста таблицы очищаются; `test_db.test_migrations_match_models` сверяет схему миграций с моделями. Postgres не запущен — пропуск, `TEST_REQUIRE_DB=1` — ошибка |
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
  ACCESS_CODE {
    uuid id PK "новое: код доступа к проекту"
    uuid project_id FK
    string code_hash UK
    string label "кому выдан"
    uuid created_by FK
    timestamp expires_at
    timestamp revoked_at
    int uses
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
  PROJECT ||--o{ ACCESS_CODE : "коды доступа"
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
  `studio.kind`; `app_user.account_type` — подсказка стартового экрана.
- **Связи по ключу** (решение 2026-11-03): всё, что принадлежит студии, ведёт к одному
  `studio.id` — напрямую (`studio_id`) или через проект (`project_id → project.studio_id`);
  человек связан со студией строкой `membership`. **Пространство — одно на человека**:
  `membership.user_id` уникален (миграция `0007`) — своя фирма, «Мой ремонт» или чужая фирма
  сотрудником; приглашение в другую фирму не принимается. Несколько фирм и переключатель —
  позже.
  Вид фирмы пока ни на что не влияет — заведён, чтобы потом развести права, листы и тарифы.
- **Клиент — один проект**: частичный уникальный индекс Postgres
  `project_member (user_id) WHERE role = 'client'`.
- **Проверка доступа — одно правило в двух видах**: `project_role(user, project) → роль |
  None` для запроса к проекту и `visible_projects(user)` — тот же список одним запросом по
  ключам для списка проектов: суперпользователь → всё; `membership` по `project.studio_id`;
  `project_member`; действующий `support_grant`. Что они совпадают для каждой роли и что
  студии не пересекаются — тест `test_studios_do_not_cross`.

### Вход (решения пользователя 2026-10-28)

- **Без паролей: Telegram по номеру телефона, Google или код на почту.** Apple не делаем
  ($99 в год), другие провайдеры — строкой в `oauth_account`. Новая учётка провайдера с подтверждённым email,
  который уже есть, — тот же пользователь; неподтверждённый email не привязывается.
- **Код на почту** (решение 2026-10-31): email → 6 цифр в письме → вход. Код подтверждает
  почту, поэтому вход по коду — учётка провайдера `email` с подтверждённым адресом: тот же
  email из Google — тот же пользователь. Код живёт 10 минут, действует последний; 5 неверных
  вводов — код сгорает; новый — не чаще раза в минуту и не больше 5 в час на адрес. В базе
  (`email_code`) — только sha256 «email:код». Письма — SMTP (`SMTP_HOST`…, любой сервис:
  Resend, Postmark, SES); без SMTP на http (локально) код пишется в терминал сервера, на
  https вход по коду выключен. Ограничения по IP — пока нет (до выхода к пользователям).
- **Телефон через Telegram** (решение 2026-11-01, основной вход для клиентов; SMS и Viber —
  позже, при клиентах без Telegram): страница просит билет (`login_ticket`, sha256 токена,
  10 минут, одноразовый) и открывает `t.me/<бот>?start=<токен>`; человек жмёт Start и кнопку
  «Поделиться номером» — бот получает его контакт (номер подтверждён самим Telegram, чужой
  контакт отклоняется), ставит номер в билет; страница опрашивает билет и входит. Учётка —
  провайдер `telegram` с `app_user.phone` («+380…»): тот же номер — тот же пользователь.
  `SHTROBA_SUPERUSERS` и `SHTROBA_OWNER` принимают телефоны наравне с почтой. Бот —
  `TELEGRAM_BOT_TOKEN` (`api/telegram.py`): на https — вебхук с секретом в заголовке, ставится
  при старте; локально на http сервер сам опрашивает Bot API в фоне. Правила на базе —
  `db/telegram_login.py`, миграция `0005`.
- **Два типа учётки** (`account_type`, выбор при первом входе, не меняется): `client` —
  хозяин квартиры, личное пространство (`studio.kind = personal`) на один проект, может
  загрузить свой план сам и позвать монтажника; `pro` — студия или монтажник, своя студия,
  проектов сколько угодно. Приглашённый без типа получает его по роли приглашения.
- **Сессия** — `user_session`: случайный токен в cookie `shtroba_session` (HttpOnly,
  SameSite=Lax, Secure на https, 30 дней), в базе только sha256. Выход — удаление сессии.
- **Приглашение** (`invite`) — одноразовая ссылка на 7 дней `…/?invite=<токен>`; ключ —
  сама ссылка, email не сверяется (студия видит, кто принял). Хозяин квартиры зовёт в свой
  проект только монтажника.
- **Код доступа к проекту** (`access_code`, решение 2026-11-02): студия выдаёт код
  `floorplan-engine access code projects/<имя> [--label "Иван"] [--days 30]` и передаёт его
  человеку как есть — в переписке или на словах. На экране входа внизу — поле «Код от студии»:
  ввёл — открылся этот один проект, только чтение (роль `viewer`: ни ответов, ни правки
  трасс, ни выбора варианта). Учётки не появляется: в подписанной cookie — id кода, каждый
  запрос проверяет, что код не отозван и не истёк. Код — 8 знаков без 0/O и 1/I, показывается
  как «XXXX-XXXX», в базе только sha256; действует 30 дней (до 365), входов сколько угодно.
  Проекта ещё нет в базе (владелец не входил) — `access code` записывает его «без
  владельца» (студия `kind = unowned`, без участников; то же — `access link` без `--owner`),
  при входе владельца `adopt_folders` переводит такие проекты к нему. Список — `access
  codes`, отзыв — `access revoke-code <имя> <id>` (входы кончаются со следующего запроса). Чужой, отозванный и истёкший код отвечают одинаково; больше 20
  неверных кодов с адреса за 10 минут — 429. Выдача из просмотра (кнопка у проекта) — позже.
  Постоянный код с известным значением — переменная `SHTROBA_ACCESS_CODES=папка=КОД,…`:
  при старте сервис записывает его в базу (`ensure_code`, срок 10 лет; отозванный снова
  действует — переменная важнее отзыва, действующий код не трогается и не журналируется);
  папки с таким именем нет или код уже у другого проекта — предупреждение в лог, строка
  проекта не создаётся; параллельный старт двух процессов не роняет второй. Для тестов,
  чтобы код не выдавать вручную против базы сервера.
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
| `service/db/access.py` | Правила: роль в проекте (`project_role`), видимые проекты (`visible_projects`), права (`can`), пользователи OAuth, тип учётки, сессии, приглашения, доступ поддержки, журнал |
| `service/db/email_codes.py` | Код на почту: выдать (`issue_code`, частота), проверить (`check_code`, срок, попытки) |
| `service/db/access_codes.py` | Код доступа к проекту: выдать (`issue_code`), постоянный из окружения (`ensure_code`), вход (`use_code`), проверка на каждом запросе (`active_code`), список и отзыв (`list_codes`, `revoke_code`) |
| `service/db/telegram_login.py`, `service/api/telegram.py` | Вход через Telegram: билеты (`issue_ticket`, `bind_chat`, `confirm_phone`, `claim_ticket`, номер — `normalize_phone`); бот — клиент Bot API, разбор обновлений (`handle_update`), вебхук или опрос |
| `service/db/admin.py`, `service/api/admin.py` | Админка платформы: виды (студии, пользователи, проекты, журнал) и изменения (участники, роли, приглашения, коды, поддержка, блокировка) по правилам `access.py`; API `/api/admin/*` — только действующий суперпользователь (иначе 403), нарушение правила — 409 с причиной |
| `service/api/mail.py` | Письмо с кодом на языке страницы: SMTP или лог (локально) |
| `service/api/auth.py` | Веб: настройки из окружения (`AuthConfig.from_env`), Google через Authlib, код на почту (`/api/auth/email/start`, `/verify`), код доступа (`/api/auth/code`, подбор — `CodeLimiter`), маршруты `/api/auth/*` и `/api/invites/*`, проверка доступа к `/api/projects/{имя}/…` (нет входа — 401, чужой проект — 404, нет права — 403) |
| `web/src/pages/Gate`, `widgets/TelegramLogin`, `widgets/EmailLogin`, `widgets/CodeLogin`, `shared/auth.ts` | Экран входа (Telegram, Google, код на почту, код доступа к проекту), выбор «кто вы», принятие приглашения, «Выйти» |

Пока проекты живут в папках, строка `project` связана с папкой по `slug`:
`floorplan-engine access link projects/<имя> --owner <email>` (владелец уже входил и выбрал
тип), ссылка-приглашение — `floorplan-engine access invite projects/<имя> --role client`,
код доступа без учётки — `floorplan-engine access code projects/<имя>`.
Папка без строки в базе видна только суперпользователю и гостю. На сервере связывает сам
вход (решение 2026-11-01): пользователь с почтой `SHTROBA_OWNER` входит или выбирает «Фирма» —
все папки без строки уходят в его студию (`access.adopt_folders` из `Auth._adopt`); новые папки
после деплоя подхватываются при следующем входе. Ни консоли, ни перезапуска не нужно.

**Админка платформы** (решение 2026-11-03): отдельный фронт `admin/` для владельца платформы
(суперпользователя) над API `/api/admin/*`. Студиям своим доступом управлять — потом, в
настройках студии просмотра. Изменения из админки не пишут в таблицы напрямую, а идут через
правила доступа: человек — в одном пространстве, у клиента — один проект, у студии остаётся
владелец, хозяин квартиры не бывает сотрудником фирмы; каждое — в журнал (`admin_*`).
Админка живёт на домене просмотра по пути `/admin/` (Caddy), поэтому вход общий — через
просмотр. Состояние приглашения, кода и доступа поддержки API отдаёт словом (`active`,
`accepted`, `revoked`, `expired`), людей и студии из журнала — с именами. Устройство фронта —
`admin/README.md`.

**Папки студий** (решение 2026-11-03): у каждой студии свои файлы — проекты, прайс
`prices.yaml` и профиль `studio.yaml` — в своей папке корня просмотра (`access.studio_folder`,
поле `studio.folder`, миграция `0008`): `<корень>/<studio.id>/`. Корень — это `projects/`
оператора: он принадлежит одной студии, той, что забрала папки корня (`access.claim_root` —
из `adopt_folders` и `access link`), и проектам «без владельца». Ядро не меняется: прайс и
профиль оно находит в папке над проектом, то есть в папке его студии. Новая студия прайс
корня не наследует (это цены другой студии): без своего — цены сервиса. Рыночная выборка
`market.yaml` — общая, в корне. Запрос к проекту (`Auth.check`) кладёт папку студии проекта в
`request.state.folder`, прайс — папку студии вызывающего. Имя проекта в адресе пока
уникально во всей базе (`project.slug`); уникальность внутри студии — вместе с переходом
адресов на id.

Окружение — в `.env.example` и docstring `service/api/auth.py`. Локально — файл `.env` в корне
репозитория: его читают команды сервиса (`view`, `dev`, `serve`, `access`, `analyze`;
`cli.load_env`), заданное в окружении главнее; `build` и `check` его не читают. Скачанный из
консоли `client_secret_*.json` в git не кладётся (`.gitignore`): id и секрет — в `.env`. На Railway: Postgres (адрес
`postgresql://…` код сам переводит на psycopg 3), `SHTROBA_AUTH=on`, `SHTROBA_SECRET`,
`SHTROBA_PUBLIC_URL`, `GOOGLE_CLIENT_ID` и `GOOGLE_CLIENT_SECRET`, `SHTROBA_SUPERUSERS`;
миграции применяет `deploy/start.sh` при старте. В Google Cloud Console у OAuth-клиента
адрес возврата — `<SHTROBA_PUBLIC_URL>/api/auth/google/callback`.

## Переезд проектов из папок в базу (этап Б)

Решения пользователя 2026-11-03:
- **Правда — база.** Проект живёт в базе; папка — только рабочая копия. Для работы в Claude
  Code: `floorplan-engine project pull` выгружает проект в папку, `push` заливает правки новой
  версией модели (с проверкой, что в базе за это время не появилась более новая). Деплой
  проекты больше не копирует; `projects/` в git перестаёт быть источником.
- **Модель — YAML-текст и jsonb-копия.** Правда — текст каждого файла модели как есть
  (комментарии «# PDF, масштаб», пометки допущений и порядок полей сохраняются, выгрузка в
  папку — байт в байт); рядом — разобранная копия в jsonb для запросов и админки.
- **Файлы — сначала volume, S3 потом.** Интерфейс `ObjectStore` (ключ → байты) с реализацией
  «папка по ключу» на volume сервера; файл адресуется ключом из базы, а не папкой проекта.
  R2/S3 — второй реализацией, когда понадобится.

Ядро не меняется: оно по-прежнему собирает из папки. Сервис выкладывает версию модели,
источники, прайс и профиль студии во временную папку, собирает и забирает результат.

| Шаг | Что |
| --- | --- |
| Б1 | `ObjectStore` (локальная папка по ключу); `model_version` — все файлы модели (+ `plumbing.yaml`, `variant.yaml`) текстом и jsonb-копией; прайс студии — текстом YAML (с комментариями) |
| Б2 | Проект из базы: выложить версию во временную папку, собрать, забрать `out/` в хранилище (`build`, `build_file`); тесты на круг «база → папка → сборка → хранилище» |
| Б3 | `project push` / `pull`: папка ↔ база (новая версия, источники, сборка); импорт текущих проектов |
| Б4 | Просмотр из базы: проекты и листы — по id проекта из хранилища; правка трасс и вариант — новой версией модели и пересборкой; прайс и профиль — из базы; адреса `web/` — по id, `slug` уникален внутри студии |
| Б5 | Деплой: `start.sh` проекты не копирует; перенос проектов с volume в базу и сверка |
| Б6 | API сервиса (`app.py`, `Workflow`) на базе, проверка доступа в нём (техдолг); кэш выжимок, расход LLM — в базе |
| Б7 | Папки проектов на сервере удаляются после сверки; `FileStorage` остаётся для тестов |

Команды (Б3, `service/sync.py`): `floorplan-engine project push <папка> [--owner]`, `project pull
<имя> [--to] [--force]`, `project import <папка проектов> --owner` (всё сразу, с прайсом и
профилем студии), `studio push|pull <папка> --owner`. Папка помнит, откуда она, в скрытом
`.shtroba.yaml` (id проекта и версия; в git не идёт): push откажет, если в базе за это время
появилась версия новее (правка трасс на сервере — сначала pull), pull откажет затирать правки,
которых нет в базе (`--force` — затереть). Новая версия модели — только если файлы изменились;
исходники — по хешу, без повторов. Хранилище файлов — папка из `SHTROBA_OBJECTS` (по умолчанию
`data/objects`).

Просмотр из базы (Б4, `service/api/viewer_db.py`) включается `SHTROBA_STORAGE=db` (только со
входом): проект — по id (старая ссылка по имени открывается), листы и `out/` — из последней
сборки в хранилище, модель — из последней версии; правка трасс и вариант — той же функцией ядра
во временной папке, новой версией модели от пользователя (`model_version.user_id`) и
пересборкой; прайс — строка `price_list` студии вызывающего, рыночная выборка — файл в корне.
Без переключателя просмотр работает с папкой, как раньше, — до Б7.

Имя проекта (`slug`) уникально внутри студии (миграция `0010`): у двух студий может быть по своему
`kv42`. Ссылка по имени ищет среди проектов, которые видит вызывающий, и открывается, только если
имя там одно; без вызывающего (команды CLI) имя должно быть одно во всей базе, иначе — «укажите
студию» (`--owner`) или id. Id открывает всегда; доступ проверяется отдельно.

Эксплуатация: резервные копии Postgres и хранилища, миграции Alembic при выкладке, секреты
(`DATABASE_URL`, ключи хранилища) — из окружения сервера.
