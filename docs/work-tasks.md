# Монтаж по задачам

Решение 2026-11-11. Статус: бэк сделан (шаг 1: черновик в ядре, таблицы, права, API, тесты);
фронт (шаг 2) — нет. Отличия от первоначального проекта — раздел «Как сделано на бэке» в конце.

Утверждённый с заказчиком проект делится на задачи монтажа: «Штробы и подрозетники»,
«Прокладка кабеля», «Установка щита», «Опрессовка водопровода»… Задача — карточка как в
трекере: исполнитель, статус, позиции с ценой, план и факт, фото, комментарии, оплаты, история.
Монтажник сдаёт задачу с фото, заказчик принимает или возвращает с комментарием, студия
отмечает оплату — идут дальше.

Зачем Штробе: фото открытых штроб до штукатурки, привязанные к проекту, — исполнительная
документация «что в стене», которую клиенту больше никто не даёт; сумма этапа и критерий
приёмки уже есть в смете и в составе работ (`electrical/work_scope.yaml`, поле `result`).

## Кто что считает

| Что | Где | Почему |
| --- | --- | --- |
| Черновик задач: какие позиции сметы в какой задаче, порядок, зависимости, критерий приёмки, нужно ли фото | ядро, детерминированно: `electrical/stages.py` + `stages.yaml`, `plumbing/stages.py` + `stages.yaml`, сборка — `pipeline/work_plan.py`; результат — ключ `work_plan` в `.epd` | это свойство проекта и сметы, как `work-scope.md`; одна и та же модель даёт один и тот же черновик |
| Задачи, статусы, факт, цены после правки, фото, комментарии, оплаты | только база сервиса (`service/db/`), фото — `ObjectStore` | это состояние работ, а не модель квартиры: в `projects/<имя>/` и в YAML его нет |

Ядро о задачах в базе не знает. Сервис черновик не пересчитывает: берёт `work_plan` из `.epd`
последней сборки.

## Черновик из сметы

Шаблон этапов — данные (`stages.yaml` рядом с модулем), каждая позиция сметы (базовый ключ,
`split_key`) входит ровно в один этап; тест проверяет, что все ключи `LINES` разложены и
лишних нет (как `missing_scope` у состава работ). Позиция, которой нет в смете проекта, в
задачу не попадает; этап без позиций в черновик не попадает.

Электрика (`electrical/stages.yaml`; `prefix.*` — все ключи с этим началом):

| # | Этап (`key`) | Работы | Материалы | Фото при сдаче | После |
| --- | --- | --- | --- | --- | --- |
| 1 | Штробы, проходы, подрозетники (`chases`) | `work.chase`, `work.chase_wide` (обе — с материалом стены: `work.chase.brick`…), `work.wall_hole`, `work.wall_hole_large`, `work.socket_box` | `socket_box` | `optional` | — |
| 2 | Прокладка кабеля (`cable`) | `work.cable` (маркировка концов входит в неё: `work.marking` снят 2026-11-11), `work.conduit` | `cable`, `conduit`, `conduit_joint`, `conduit_entry`, `conduit_clip`, `cable_pad` | `required`: трассы до штукатурки | 1 |
| 3 | Распаечные коробки (`boxes`) | `work.junction_box` | `junction_box`, `junction_box_ip`, `crimp` | `optional` | 2 |
| 4 | Установка корпуса щита (`board`) | `work.board_install` | `board_enclosure`, `dc_enclosure` (щит АКБ) | `optional` | — |
| 5 | Замер изоляции (`insulation`) | `work.insulation_test` | — | `required`: протокол, фото или PDF | 2, 3 |
| 6 | Черновой свет (`rough_light`) | `work.rough_light`, `work.rough_switch` | `rough_holder`, `rough_lamp`, `rough_switch` | `none` | 2 |
| 7 | Сборка щита (`assembly`) | `work.board_module` | `breaker`, `diff`, `rcd`, `input`, `relay`, `spd`, `changeover`, `ats`, `contactor`, `feed`, `output`, `dc_battery`, `dc_breaker`, `dc_spd` | `optional` | 4, 5 |
| 8 | Механизмы и светильники (`devices`) | `work.mechanism`, `work.led_psu`, `work.led_psu_din` | `socket`, `switch1`, `switch2`, `pass_switch`, `data`, `tv`, `frame`, `light`, `downlight`, `pendant`, `sconce`, `led_output`, `outlet`, `led_strip`, `led_psu`, `led_psu_din` | `optional` | 7 |

Сантехника (`plumbing/stages.yaml`):

| # | Этап (`key`) | Работы | Материалы | Фото | После |
| --- | --- | --- | --- | --- | --- |
| 1 | Штробы и проходы под трубы (`chases`) | `work.chase_pipe`, `work.chase_sewer`, `work.chase_sewer_floor`, `work.wall_hole` | — | `optional` | — |
| 2 | Канализация (`sewer`) | `work.sewer_pipe`, `work.riser_tee`, `work.sewer_box` | `sewer.*` | `optional` | 1 |
| 3 | Водопровод (`water`) | `work.input`, `work.water_pipe`, `work.water_outlet` | `water.*` | `required`: трубы до стяжки | 1 |
| 4 | Опрессовка водопровода (`pressure`) | `work.pressure_test` | — | `required`: манометр | 3 |

«Да» первоначальной таблицы стало `optional`, «да, обязательно» и протокол — `required`, «нет» —
`none`. Критерий приёмки электрики — `result` работ этапа из `work_scope.yaml`; у сантехники
состава работ нет, критерий записан у каждого этапа в `plumbing/stages.yaml`. Этапа без позиций
в смете нет, и задачи после него идут после его предшественников: нет коробок — замер изоляции
после прокладки кабеля, нет корпуса щита — сборка щита после замера.

Правда — `stages.yaml` и тест полноты (`tests/electrical/test_stages.py`,
`tests/plumbing/test_stages.py`); таблица выше — их копия на 2026-11-11. Этапы двух разделов в плане идут одним списком, у каждой задачи
`domain`: `electrical` | `plumbing`. Электрика и сантехника друг от друга не зависят.

Вариант проводки (`variant.yaml`) черновик меняет только через смету: нет гофры — нет
`work.conduit`, нет чернового света — нет этапа 6. Порядок «до или после штукатурки»
(`plaster`) в MVP не меняет этапы; штукатурка — не наша работа и задачей не бывает.

### Ключ `.epd` `work_plan`

```json
{
  "work_plan": {
    "currency": "UAH",
    "tasks": [
      {
        "key": "electrical.cable",
        "domain": "electrical",
        "order": 2,
        "title": "Прокладка кабеля",
        "after": ["electrical.chases"],
        "photo": "required",
        "result": ["кабель лежит по трассе и закреплён, …"],
        "lines": [
          {"key": "work.cable", "kind": "work", "title": "Прокладка кабеля", "unit": "м",
           "qty": 609.4, "price": 34, "sum": 20719.6}
        ],
        "work_total": 29860.6,
        "material_total": 59012.2,
        "unpriced": 0
      }
    ]
  }
}
```

Тексты — на языке проекта. `price: null` — цены нет в прайсе («цена уточняется»), сумма
считается без неё и задача помечена (`unpriced` — строк без цены). Валюта — валюта смет
(`грн`). Ключ необязательный, поэтому `FORMAT_VERSION` не повышался (`docs/development.md`;
повышение отрезало бы просмотр от всех сборок до правки `web/`). Формат — `docs/epd-format.md`.

## Задача в базе

```mermaid
erDiagram
  WORK_PLAN ||--o{ WORK_TASK : tasks
  WORK_TASK ||--o{ WORK_LINE : lines
  WORK_TASK ||--o{ WORK_PHOTO : photos
  WORK_TASK ||--o{ WORK_COMMENT : comments
  WORK_TASK ||--o{ WORK_PAYMENT : payments
  WORK_PLAN {
    uuid id PK
    uuid project_id FK
    uuid model_version_id FK "версия, по которой утверждали"
    uuid build_id FK "сборка, из которой взят черновик"
    string state "draft | proposed | approved | closed"
    uuid approved_by FK
    timestamp approved_at
  }
  WORK_TASK {
    uuid id PK
    uuid plan_id FK
    string key "electrical.cable; у ручной задачи пусто"
    string domain "electrical | plumbing | other"
    int position "порядок в списке"
    string title
    text description
    string status "proposed | todo | in_progress | review | returned | accepted"
    bool extra "доп. работа вне утверждённого плана"
    string photo "required | optional | none"
    jsonb result "критерий приёмки, строки"
    jsonb after "ключи или id задач, после которых"
    uuid assignee_id FK
    bool materials_included "материалы в цене задачи"
  }
  WORK_LINE {
    uuid id PK
    uuid task_id FK
    string key
    string kind "work | material"
    string title
    string unit
    float plan_qty
    float fact_qty "вписывает монтажник; пусто — как в плане"
    float price "из сметы; студия может поправить"
  }
  WORK_PHOTO {
    uuid id PK
    uuid task_id FK
    string object_key "ObjectStore: projects/<id>/work/<task>/<photo>.<ext>"
    string content_type
    string caption
    string target "объект чертежа тип:id, позже"
    uuid user_id FK
    timestamp created_at
  }
  WORK_COMMENT {
    uuid id PK
    uuid task_id FK
    uuid user_id FK
    string author_label "у кода доступа — его подпись"
    text text
    string kind "comment | return | status"
  }
  WORK_PAYMENT {
    uuid id PK
    uuid task_id FK
    numeric amount
    date paid_on
    string note
    uuid recorded_by FK
  }
```

Сумма задачи — Σ по строкам `(fact_qty ?? plan_qty) × price`, работы и материалы отдельно;
материалы входят в сумму, если `materials_included`. Сумма не хранится, её считает код.
Оплачено — Σ `work_payment`; «оплачено» на карточке, когда оплачено ≥ суммы. Аванс — это просто
оплата до приёмки.

### Жизнь плана

1. Студия: «Создать задачи из сметы» — `work_plan` в состоянии `draft` из последней сборки,
   задачи из `.epd` `work_plan`. Студия правит: объединяет, переименовывает, меняет цены,
   добавляет свои задачи, назначает монтажника.
2. Студия: «Отправить заказчику» → `proposed`. Заказчик видит план и общую сумму.
3. Заказчик: «Утвердить» → `approved`, задачи — `todo`. План запоминает версию модели.
4. Модель после утверждения меняется — план остаётся на своей версии; новая работа — задача
   с `extra: true`, она начинается в `proposed`, пока заказчик не согласит цену.
5. Все задачи приняты и оплачены — студия закрывает план (`closed`).

Один активный план на проект (MVP).

### Статусы задачи

```mermaid
stateDiagram-v2
  [*] --> proposed: доп. работа
  proposed --> todo: заказчик согласовал
  [*] --> todo: план утверждён
  todo --> in_progress: монтажник взял
  in_progress --> review: сдал (фото, если нужно)
  review --> accepted: заказчик принял
  review --> returned: заказчик вернул с комментарием
  returned --> in_progress: монтажник взял снова
  returned --> review: исправил и сдал
```

- Сдать задачу с `photo: required` без фото нельзя (ошибка с текстом для пользователя).
- Вернуть — только с комментарием.
- `after` — мягкая зависимость: карточка показывает «ждёт: Прокладка кабеля», взять её в
  работу может студия, монтажник — нет.
- Каждая смена статуса — строка `work_comment` с `kind: status` и запись в `audit_event`.

## Права

Новые действия в `service/db/access.py`:

| Действие | Кто | Что |
| --- | --- | --- |
| `view` (есть) | все роли проекта | видеть план и задачи |
| `work_do` | owner, designer, installer, superuser | взять, сдать, факт по строкам, фото, комментарий |
| `work_accept` | owner, designer, client, client_code, superuser | утвердить план, принять, вернуть, согласовать доп. работу, комментарий |
| `work_manage` | owner, designer, superuser | создать план, править задачи и цены, назначить, удалить, оплаты, закрыть план |

Код просмотра (`viewer`) только смотрит. Удалить фото может его автор и студия.

## API

Только в режиме базы (`service/api/viewer_db.py`); у просмотра папок (`view` без базы) задач
нет, вкладка скрыта (`GET /api/projects/{key}` отдаёт `work: false`).

| Метод | Путь | Право | Что |
| --- | --- | --- | --- |
| GET | `/api/projects/{key}/work` | view | план, задачи со строками, суммами, фото (метаданные), комментариями, оплатами; `draft_available` |
| POST | `/api/projects/{key}/work/plan` | work_manage | создать план из черновика последней сборки |
| POST | `/api/projects/{key}/work/plan/{action}` | по действию | `propose` (manage), `approve` (accept), `close` (manage) |
| POST | `/api/projects/{key}/work/tasks` | work_manage | новая задача; после утверждения — `extra: true` |
| PATCH | `/api/projects/{key}/work/tasks/{id}` | work_manage | название, описание, порядок, исполнитель, `materials_included`, `photo` |
| DELETE | `/api/projects/{key}/work/tasks/{id}` | work_manage | только `todo` / `proposed` без фото и оплат |
| POST | `/api/projects/{key}/work/tasks/{id}/status` | по переходу | `{to, comment?}` |
| PATCH | `/api/projects/{key}/work/tasks/{id}/lines/{line}` | work_do (факт), work_manage (цена) | `{fact_qty?, price?}` |
| POST | `/api/projects/{key}/work/tasks/{id}/lines` | work_manage | своя строка |
| POST | `/api/projects/{key}/work/tasks/{id}/photos` | work_do, work_accept | multipart, до 15 МБ, jpeg/png/webp/heic, pdf (протокол) |
| GET | `/api/projects/{key}/work/photos/{id}` | view | файл |
| DELETE | `/api/projects/{key}/work/photos/{id}` | автор, work_manage | |
| POST | `/api/projects/{key}/work/tasks/{id}/comments` | work_do, work_accept | `{text}` |
| POST | `/api/projects/{key}/work/tasks/{id}/payments` | work_manage | `{amount, paid_on, note?}` |
| DELETE | `/api/projects/{key}/work/payments/{id}` | work_manage | |

Ошибки — по-русски, как у остальных ручек просмотра. Деньги в ответе — числа, формат — на фронте.

## Фото

`ObjectStore` (`service/objects.py`): в разработке и сейчас на сервере — `LocalObjectStore`
(том Railway), позже R2/S3 за тем же протоколом, код задач не меняется. Ключ —
`projects/<project id>/work/<task id>/<photo id>.<ext>` (функция `work_photo_key` рядом с
`source_key`). Удаление проекта удаляет и префикс `work/`. Превью, EXIF-поворот и сжатие — шаг 2.

## Просмотр (`web/`)

Вкладка «Монтаж» рядом с листами; есть, когда `work: true`.

- **Студия** (`STUDIO_ROLES`) — доска: колонки «К работе / В работе / На приёмке / Возвращено /
  Принято», переключатель «электрика / сантехника / всё». Сверху — прогресс: принято N из M,
  оплачено X из Y.
- **Заказчик** (`CLIENT_SIDE`) — список по порядку работ, крупно: статус, сумма, что нужно от
  него («Примите работу», «Согласуйте доп. работу»). С телефона.
- **Карточка задачи** (боковая панель, на телефоне — весь экран): описание, критерий приёмки
  чекбоксами, строки план/факт/цена/сумма, фото (загрузка `accept="image/*,application/pdf"`,
  `capture` на телефоне), комментарии лентой, оплаты, кнопки по роли и статусу, «ждёт: …».
- Пустое состояние у студии — «Создать задачи из сметы»; у заказчика — «Студия ещё готовит
  план работ».
- Строки — через `shared/i18n` (ru, uk, en).

## Как сделано на бэке (шаг 1, 2026-11-11)

Код: ядро — `electrical/stages.py` (+ `stages.yaml`), `plumbing/stages.py` (+ `stages.yaml`),
`pipeline/work_plan.py`, ключ `work_plan` манифеста; сервис — таблицы и миграция `0013`
(`docs/database.md`), правила — `service/db/work.py` и `work_records.py`, API —
`service/api/work.py` (контракт — `docs/service-api.md`, «Монтаж по задачам»), права —
`work_do`, `work_accept`, `work_manage` в `service/db/access.py`, ключи фото —
`objects.work_photo_key`. Отличия от проекта выше:

- `FORMAT_VERSION` не повышен: ключ необязательный (см. выше).
- Задачи черновика идут одним списком по номеру этапа, при равном — сначала электрика (штробы
  обоих разделов — первыми); `order` — номер этапа в шаблоне своего раздела.
- До утверждения задачи плана — в статусе `proposed`; `approve` переводит их в `todo`. Статусы
  меняются только в утверждённом плане; фото и оплаты — тоже после утверждения; в закрытом
  плане ничего не меняется.
- Деньги (цены строк, свои строки, `materials_included`) меняются, пока план не утверждён, и у
  доп. работы до согласования; после — `409` «сумма задачи согласована с заказчиком».
  Название, описание, порядок, исполнитель, `photo` и `after` — всегда, пока план не закрыт.
- Добавлено к API: `POST /work/plan/discard` — удалить ещё не утверждённый план (пересоздать
  черновик после пересборки); `after` в `PATCH` задачи (ссылки на задачи плана); в ответе —
  `waiting`, `money_editable`, суммы задачи и плана, `assignees` (для студии) и `can`. Каждая
  запись отвечает всем состоянием, как `GET /work`.
- `close` проверяет, что все задачи приняты и оплачены (`paid ≥ total`).
- Удалить фото: автор — пока задача не принята; студия — всегда. У кода доступа учётки нет:
  его фото удаляет только студия. Комментарий и фото с кода подписаны «код: <подпись>»,
  утверждение планом с кода — `approved_label`.
- `work_comment.status` — новый статус у записей `status` и `return`; у плана — `currency`,
  `approved_label`, `closed_at`; у фото — `file_name`, `size`, `author_label`.
- Удаление проекта с файлами (`project_store.delete_project`, снимает и префикс `work/`)
  готово, но маршрута удаления проекта в режиме базы пока нет: ни один вызов его не делает.
- Объединять задачи студия пока не может: в API нет переноса строк между задачами.

## Шаги

1. **Бэк** (сделан 2026-11-11): черновик в ядре (`stages.py` × 2, `stages.yaml` × 2,
   `pipeline/work_plan.py`, ключ `.epd` без смены версии), таблицы и миграция, репозиторий
   задач, права, API, тесты, доки (`modules.md`, `database.md`, `service-api.md`,
   `epd-format.md`, `status.md`).
2. **Фронт**: вкладка, доска, список, карточка, загрузка фото, тесты, Storybook.
3. Потом: привязка фото к стене на чертеже, PDF-акт по задаче, превью фото, уведомления
   (почта, Telegram), оплата через сервис.
