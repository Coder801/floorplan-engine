# API сервиса Штроба

Сервис принимает источники проекта (PDF, JPEG, эскизы), задаёт уточняющие вопросы,
принимает ответы и собирает чертёж: `project.dxf` для AutoCAD и `project.epd` для кабинета
(формат описан в [epd-format.md](epd-format.md)).

Запуск:

```bash
uv run shtroba serve --data data/projects --port 8000
```

Интерактивная документация OpenAPI открывается по адресу `http://127.0.0.1:8000/docs`.
Собранные проекты из `projects/` смотрят в браузере другой командой — `shtroba view` (README).
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

`analyze` и `answers` отвечают `202` сразу, а работа идёт в фоне. Опрашивайте
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
| `rejected` | Источники не годятся: ни на одном чертеже нет масштаба, хватающих размеров или уверенных подписей (LLM-анализатор, пока модели нет). Модель не вызывалась | Показать `message` с причиной по файлам и попросить PDF-экспорт или скан от 300 dpi; после новых источников — снова `POST /analyze` |
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
