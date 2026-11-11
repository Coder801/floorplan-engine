# API сервиса Shtroba

Сервис принимает источники проекта (PDF, JPEG, эскизы), задаёт уточняющие вопросы,
принимает ответы и собирает чертёж: `project.dxf` для AutoCAD и `project.epd` для кабинета
(формат описан в [epd-format.md](epd-format.md)).

Запуск:

```bash
uv run floorplan-engine serve --data data/projects --port 8000
```

Без входа API открыт всем, поэтому `serve` без `SHTROBA_AUTH=on` слушает только локальный адрес.
Со входом — те же правила, что в просмотре (`service/api/project_guard.py`): нет сессии — `401`,
чужой проект — `404`, нет права — `403`. Читать может любая роль проекта, отвечать на вопросы —
право `answer`, создавать, загружать модель, запускать анализ и удалять — право `manage`
(владелец, проектировщик, суперпользователь). Новый проект создаёт человек с учётной записью, в
своём пространстве: нужно быть его владельцем, у хозяина квартиры — один проект. Код доступа и
гость отладки проект не создают. Проект связан с базой строкой `project` (`slug` — id сервиса);
папки, созданные до включения входа, такой строки не имеют, и видит их только суперпользователь.
Удаление проекта журнал не стирает: записи остаются, id, имя и студия проекта — в `payload`.

Интерактивная документация OpenAPI открывается по адресу `http://127.0.0.1:8000/docs`.
Собранные проекты из `projects/` смотрят в браузере другой командой — `floorplan-engine view` (README).
Анализатор выбирается флагом `--analyzer`: `manual`, `claude-code` (подписка) или `api` (ключ).
Подробности — в README, раздел «Сервис».

## Цикл работы с проектом

```
POST /projects                       создать проект, загрузить источники      → created
POST /projects/{id}/analyze          анализ (в фоне)                           → analyzing → …
GET  /projects/{id}                  ждать, пока state не analyzing / building
  needs_answers → GET  /projects/{id}/questions
                  POST /projects/{id}/answers   (в фоне)                       → building → …
  ready         → GET  /projects/{id}/files/project.epd   (и project.dxf, report.md)
  insufficient  → данных мало, см. GET /projects/{id}/report
  rejected      → по источникам ничего не построить, модель не вызывалась (причина — message)
  needs_model   → модель нужно доработать: сейчас это делает оператор (см. ниже)
```

`analyze` и `answers` отвечают `202` сразу, а работа идёт в очереди (два проекта одновременно).
Задача хранится в проекте (`task` в `ProjectInfo`), поэтому рестарт её не теряет: при старте
сервис продолжает работу, прерванную перезапуском, — не больше двух запусков на задачу, потом
`failed` с причиной в `message`. Повтор платный: шаги LLM прерванной задачи оплачиваются заново, а
`llm_cost_usd` считает только последний запуск (всё — в `usage.jsonl`). На папку данных — один
процесс сервиса. Опрашивайте
`GET /projects/{id}` раз в 1–2 секунды, пока `state` равно `analyzing` или `building`.
Пока проект занят, запросы `questions`, `report`, `analyze` и `answers` возвращают `409`.

## Состояния проекта

| state | Значение | Что делать |
| --- | --- | --- |
| `created` | Источники загружены | `POST /analyze` |
| `analyzing`, `building` | Идёт работа | Ждать |
| `needs_answers` | Есть открытые вопросы | Показать вопросы и отправить ответы. Если план строится, черновик (`files`) уже доступен |
| `needs_model` | Модель нужно доработать: нет данных анализа, ошибки в модели или текстовые ответы ждут разбора. Причина — в `message` | С LLM-анализатором — повторить `POST /analyze`. С ручным — оператор загружает модель |
| `ready` | Чертёж собран | Скачать файлы. Если раунды вопросов кончились, проект собран по допущениям, оставшиеся вопросы есть в отчёте |
| `insufficient` | План построить нельзя, а спрашивать больше нечего | Показать отчёт |
| `rejected` | Источники не годятся: ни на одном чертеже нет масштаба, хватающих размеров или уверенных подписей, или пришёл только DWG/DXF (их чтение в разработке; LLM-анализатор, пока модели нет). Модель не вызывалась | Показать `message` с причиной по файлам и попросить PDF-экспорт или скан от 300 dpi; после новых источников — снова `POST /analyze` |
| `failed` | Внутренняя ошибка | `message`, лог сервиса |

Раундов вопросов не больше трёх. После третьего сервис собирает проект по допущениям, если
план строится, иначе ставит `insufficient`.

## Запросы

### `POST /projects`

`multipart/form-data`: поле `name` и одно или несколько полей `files`, каждый файл до 50 МБ.
Файлы `intake.yaml`, `room.yaml`, `electrical.yaml` и `answers.yaml` ложатся в модель проекта, а не в
источники: так заводится эталон с готовой моделью, дальше — `POST /analyze`.
Ответ `201` — объект `ProjectInfo`:

```json
{
  "id": "0824a9947b514ca1b1e195aa1fcf44e5",
  "name": "Вавилових 11",
  "state": "needs_answers",
  "round": 1,
  "message": "открытых вопросов: 3 — GET /projects/…/questions",
  "sources": ["source/plan.pdf"],
  "stages": [
    {"stage": "plan", "status": "questions", "builds": true, "reason": "", "open_questions": 3},
    {"stage": "electrical", "status": "ready", "builds": true, "reason": "", "open_questions": 0}
  ],
  "files": ["report.md", "report.json", "project.dxf", "project.epd"],
  "created": "2026-10-20T12:00:00+00:00",
  "updated": "2026-10-20T12:00:05+00:00"
}
```

`llm_calls` и `llm_cost_usd` — сколько вызовов LLM-анализатора было за всё время проекта и
сколько они стоили (оценка). Подробности каждого вызова — в `usage.jsonl` проекта.

Возможные значения `stages[].status`: `ready`, `questions`, `insufficient`, `invalid`,
`blocked`, `absent`, `unsupported`.

### `DELETE /projects/{id}`

Удаляет проект целиком: источники, модель, ответы, результаты и раунды. Ответ `204`.
Пока проект занят (`analyzing`, `building`) — `409`.

### `GET /projects/{id}/questions`

Открытые вопросы текущего раунда:

```json
{
  "project": "0824…",
  "round": 1,
  "state": "needs_answers",
  "questions": [
    {
      "id": "q3",
      "stage": "plan",
      "text": "Ширина кладовки на плане не подписана: 1783 — расчёт 7245 − 5462",
      "target": "rooms.storage.walls.w2.length",
      "answer": "value",
      "unit": "mm",
      "assumption": 1783,
      "severity": "major",
      "state": "open"
    }
  ]
}
```

Поля вопроса:

| Поле | Значение |
| --- | --- |
| `severity` | `critical` — без ответа этап не строится; `major` — построено по допущению; `minor` — уточнение |
| `answer` | Какой ответ ждать: `value` — число в единицах `unit`; `choice` — одно из `options`; `text` — свободный текст |
| `audience` | Кому вопрос: `studio` (по умолчанию) или `client`. Вопрос заказчику только уточняет: `target` у него нет, ответ — `{ "text": … }`, в модель он не идёт |
| `assumption` | Что сейчас стоит в модели. Это значение можно предложить в форме по умолчанию |
| `target` | Поле модели, к которому относится вопрос. Совпадает с `o` в `.epd` по объекту: `rooms.storage.walls.w2.length` — это объект `wall:storage.w2` |

### `POST /projects/{id}/answers`

```json
{"answers": {"q1": 850, "q2": {"accept": true}, "q3": {"text": "кладовка 1800"}}}
```

| Ответ | Значение |
| --- | --- |
| Число или строка | Значение для `value` или вариант для `choice`. Подставляется в модель |
| `{"accept": true}` | Оставить допущение |
| `{"text": "…"}` | Свободный ответ, его разбирает анализатор |

Отвечать можно на часть вопросов: остальные останутся открытыми. Ответ `202`, сервис
пересоберёт проект в фоне.

Ошибки:
- `409` — проект не в состоянии `needs_answers` или такого открытого вопроса нет;
- `422` — тело запроса не по схеме.

### `GET /projects/{id}/report`

`report.json`: статусы этапов, все вопросы с весом и состоянием, ошибки и предупреждения
проверки данных.

### `GET /projects/{id}/files/{path}`

Отдаются только файлы из `files` проекта: `project.dxf`, `project.epd`, `report.md`,
`report.json`, `project.epd` (листы для показа, формат — `docs/epd-format.md`). PNG листов
сервис не пишет: кабинет рисует листы из `.epd`.

### `GET /projects/{id}/sources/{name}`

Загруженный источник, `name` — имя из `sources` без `source/`.

### `GET /projects/{id}/model/{file}`

Текущий YAML модели (`intake.yaml`, `room.yaml`, `electrical.yaml`, `answers.yaml`); `404`, если файла ещё нет.

### `PUT /projects/{id}/model/{file}`

Загрузка модели: `intake.yaml`, `room.yaml`, `electrical.yaml` или `answers.yaml`, тело — YAML,
`content-type: text/yaml`. Так работает ручной анализатор: оператор загружает модель и вызывает
`POST /analyze`. LLM-анализатор пишет модель сам, но и при нём оператор может поправить файлы.

Формат модели описан в README. Модель удобно готовить командами `/plan` и `/electrical`
в Claude Code.

## Хранение

Данные лежат в папке `--data`. Проект — это `data/projects/<id>/`:

| Путь | Содержимое |
| --- | --- |
| `source/` | Загруженные источники |
| `intake.yaml`, `room.yaml`, `electrical.yaml` | Модель |
| `answers.yaml` | Все ответы, накопленные за раунды |
| `out/` | Отчёт и результаты |
| `rounds/NNN/` | Что прислали в раунде (`answers.json`) и чем он закончился (`report.json`) |
| `service.json` | Состояние проекта |

Позже это хранилище заменят база данных и объектное хранилище, интерфейс `Storage` при этом
не изменится.

## Просмотр: монтаж по задачам (`/api/projects/{key}/work`)

Решение 2026-11-11, `docs/work-tasks.md`. Это API просмотра (`floorplan-engine view`/`dev` со входом
и базой, `service/api/work.py`, правила — `service/db/work.py`, `work_records.py`), а не API
сервиса выше. Только в режиме базы: у просмотра папок задач нет, `GET /api/projects/{key}` там
отдаёт `"work": false`, в режиме базы — `"work": true`. `key` — id проекта (или имя, как у
остальных адресов просмотра).

Доступ: middleware пускает любого, кто видит проект (`view`), чужой проект — `404`; дальше каждая
ручка проверяет своё право по роли в проекте (`service/db/access.py`):

| Право | Роли | Что |
| --- | --- | --- |
| `view` | все роли проекта, в том числе код просмотра (`viewer`) и поддержка | видеть план, задачи, фото |
| `work_do` | `owner`, `designer`, `installer`, `superuser` | взять, сдать, факт по строкам, фото, комментарий |
| `work_accept` | `owner`, `designer`, `client`, `client_code`, `superuser` | утвердить план, принять, вернуть, согласовать доп. работу, фото, комментарий |
| `work_manage` | `owner`, `designer`, `superuser` | создать, отправить, закрыть, сбросить план; задачи, цены, строки, исполнитель, удаление, оплаты; взять задачу, которая ещё ждёт другие |

Ошибки — `{"detail": "текст по-русски"}`: `403` — нет права, `404` — нет плана, задачи, строки,
фото, оплаты, `409` — не в этом состоянии (план не утверждён, сумма согласована, задача ждёт,
нужно фото…), `422` — неверное значение (текст начинается с поля: `comment: …`, `lines[0].kind: …`),
`413` — файл больше 15 МБ, `415` — не тот тип файла. Деньги — числа, формат — на фронте.

| Метод | Путь | Право | Тело | Что |
| --- | --- | --- | --- | --- |
| GET | `/work` | view | — | состояние (ниже) |
| POST | `/work/plan` | work_manage | — | план `draft` из черновика `work_plan` последней сборки; `409` — уже есть незакрытый план или в сборке нет черновика |
| POST | `/work/plan/{action}` | по действию | — | `propose` (manage): `draft` → `proposed`; `approve` (accept): `proposed` → `approved`, задачи `proposed` → `todo`, кто и когда — в плане; `close` (manage): `approved` → `closed`, только когда все задачи приняты и оплачены; `discard` (manage): удалить план `draft` или `proposed` |
| POST | `/work/tasks` | work_manage | `{title, description?, domain?: electrical\|plumbing\|other, photo?, materials_included?, lines?: [строка]}` | своя задача в конец списка; после утверждения — `extra: true`, статус `proposed`, пока заказчик не согласует |
| PATCH | `/work/tasks/{id}` | work_manage | `{title?, description?, position?, assignee_id?, materials_included?, photo?, after?}` | `position` — место в списке с 0 (остальные сдвигаются); `assignee_id` — id из `assignees` или `null`; `after` — id или ключи задач плана; `materials_included` — пока сумма не согласована |
| DELETE | `/work/tasks/{id}` | work_manage | — | только `proposed` / `todo` без фото и оплат |
| POST | `/work/tasks/{id}/status` | по переходу | `{to, comment?}` | переходы ниже; только в утверждённом плане |
| PATCH | `/work/tasks/{id}/lines/{line}` | work_do — `fact_qty`, work_manage — `price` | `{fact_qty?, price?}` | `null` — как в плане / без цены; факт — пока задача не принята, цена — пока сумма не согласована |
| POST | `/work/tasks/{id}/lines` | work_manage | `{title, kind: work\|material, unit?, qty, price?, key?}` | своя строка, пока сумма не согласована |
| POST | `/work/tasks/{id}/photos` | work_do или work_accept | multipart: `file`, `caption?` | JPEG, PNG, WebP, HEIC/HEIF, PDF (протокол), до 15 МБ; только в утверждённом плане |
| GET | `/work/photos/{id}` | view | — | файл с его `content-type` |
| DELETE | `/work/photos/{id}` | автор (до приёмки задачи) или work_manage | — | фото с кода доступа удаляет только студия: у кода нет учётки |
| POST | `/work/tasks/{id}/comments` | work_do или work_accept | `{text}` | комментарий в ленту задачи |
| POST | `/work/tasks/{id}/payments` | work_manage | `{amount, paid_on: "ГГГГ-ММ-ДД", note?}` | оплата (аванс — оплата до приёмки); только в утверждённом плане |
| DELETE | `/work/payments/{id}` | work_manage | — | |

Пути — от `/api/projects/{key}`. Пока план не закрыт, менять можно; в закрытом — ничего (`409`).

Переходы статуса (`to`) и право: `proposed → todo` — work_accept (доп. работа согласована);
`todo → in_progress` — work_do, но если задача ждёт непринятые (`waiting`), — только
work_manage; `in_progress → review`, `returned → review` — work_do, при `photo: required` нужно
хотя бы одно фото; `review → accepted` — work_accept; `review → returned` — work_accept, только с
`comment`; `returned → in_progress` — work_do. Каждый переход — запись в ленте задачи
(`comments`, `kind: status` или `return`) и в журнале (`audit_event`: `work_status`; ещё
`work_plan_<action>`, `work_plan_create`, `work_task_add`, `work_task_delete`, `work_photo`,
`work_photo_delete`, `work_payment`, `work_payment_delete`).

Ответ `GET /work` и любой записи — всё состояние, страница его просто заменяет:

```json
{
  "plan": {
    "id": "…", "state": "approved", "currency": "грн", "model_version": 3,
    "created_at": "2026-11-11T10:00:00+00:00", "approved_at": "…", "approved_by": "Иван",
    "closed_at": null,
    "totals": {"work": 52000.0, "material": 91000.0, "total": 143000.0, "paid": 20000.0,
               "tasks": 9, "accepted": 2, "settled": 1, "unpriced": 0}
  },
  "tasks": [{
    "id": "…", "key": "electrical.cable", "domain": "electrical", "position": 1,
    "title": "Прокладка кабеля", "description": "", "status": "todo", "extra": false,
    "photo": "required", "result": ["кабель лежит по трассе и закреплён, …"],
    "after": ["electrical.chases"], "waiting": [{"id": "…", "title": "Штробы, проходы, подрозетники"}],
    "assignee": {"id": "…", "name": "Петро"}, "materials_included": true, "money_editable": false,
    "lines": [{"id": "…", "key": "work.cable", "kind": "work", "title": "Прокладка кабеля",
               "unit": "м", "plan_qty": 609.4, "fact_qty": null, "price": 34.0, "sum": 20719.6}],
    "work_total": 29860.6, "material_total": 59012.2, "total": 88872.8, "paid": 0.0,
    "settled": false, "unpriced": 0,
    "photos": [{"id": "…", "url": "/api/projects/<id>/work/photos/<id>", "file_name": "IMG_1.HEIC",
                "content_type": "image/heic", "size": 812345, "caption": "", "author": "Петро",
                "user_id": "…", "created_at": "…"}],
    "comments": [{"id": "…", "kind": "status", "status": "in_progress", "text": "",
                  "author": "Петро", "user_id": "…", "created_at": "…"}],
    "payments": [{"id": "…", "amount": 10000.0, "paid_on": "2026-11-11", "note": "аванс",
                  "created_at": "…"}]
  }],
  "draft_available": true,
  "model_version": 4,
  "assignees": [{"id": "…", "name": "Петро"}],
  "can": {"work_do": true, "work_accept": false, "work_manage": true}
}
```

- `plan: null`, `tasks: []` — плана ещё нет; `draft_available` — есть ли черновик в последней
  сборке (кнопка «Создать задачи из сметы»). Показывается незакрытый план, иначе последний
  закрытый.
- Сумма строки — `(fact_qty ?? plan_qty) × price`, `null` без цены; суммы задачи — по строкам с
  ценой, работы и материалы отдельно, `total` — работы плюс материалы, если
  `materials_included`; `paid` — сумма оплат, `settled` — `paid ≥ total`. Суммы не хранятся.
- `model_version` у плана — версия модели, из которой он сделан и по которой утверждён; рядом —
  последняя версия проекта: разные — модель менялась после плана (новая работа — доп. задачей).
- `money_editable` — можно ли менять цены, строки и `materials_included`: план ещё не утверждён
  или это доп. работа, которую заказчик ещё не согласовал.
- `assignees` — только для `work_manage` (люди студии проекта и приглашённые монтажники), у
  остальных пусто. `author` у кода доступа — «код: <подпись>».
