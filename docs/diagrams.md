# Схемы системы

UML-схемы Shtroba в Mermaid: GitHub, VS Code и просмотр артефактов рисуют их сами. Это карта
для холодного читателя: что из чего состоит, кто с кем говорит и через какие состояния
проходит проект. Поток данных и таблица «кто что считает» — в [architecture.md](architecture.md),
модули по файлам — в [modules.md](modules.md).

**Схемы сверяются с кодом тестом `tests/test_diagrams.py`**: порядок слоёв — с контрактом
import-linter в `pyproject.toml`, состояния проекта — с `service/models.ProjectState`, группы
фронта и их импорты — с `web/src/structure.test.ts`, классы модели — с `model/`. Поменял слой,
состояние, группу фронта или файл модели — тест упадёт, пока схема не обновлена. Схему
контейнеров тест не проверяет: новый контейнер (сервис, хранилище, внешняя система) или новое
ребро между ними дописывай руками в том же изменении.

## Контейнеры

Два пути к одному ядру. Проектировщик работает с папкой `projects/<имя>` через CLI,
пользователи сервиса ходят из браузера в FastAPI, и правда для них лежит в Postgres. Боевой
образ один: Caddy отдаёт собранные `web/dist` и `admin/dist` и проксирует `/api`.

```mermaid
flowchart LR
    studio["Студия · заказчик · монтажник<br>браузер"]
    owner["Владелец платформы<br>браузер"]
    designer["Проектировщик · Claude Code<br>терминал"]
    subgraph image["Один Docker-образ (Railway)"]
        caddy["Caddy<br>статика web/dist, admin/dist · прокси /api"]
        web["web/ — просмотр<br>React 19 + TypeScript + Vite"]
        admin["admin/ — админка платформы"]
        api["service/api — FastAPI"]
        db[("service/db — Postgres 18<br>SQLAlchemy, Alembic")]
        files[("storage · objects<br>data/objects")]
        tasks["tasks · workflow<br>очередь, состояния проекта"]
        analysis["service/analysis<br>LLM-анализатор"]
    end
    claude["Claude<br>claude -p или Anthropic API"]
    cli["cli/ — floorplan-engine"]
    core["Ядро floorplan_engine<br>pipeline → … → model"]
    folder["projects/имя/<br>YAML, source/, out/"]
    studio -->|HTTPS| caddy
    owner -->|HTTPS| caddy
    caddy --> web & admin
    web -->|"/api: JSON, .epd"| api
    admin -->|"/api/admin"| api
    api --> db & files & tasks
    tasks --> analysis
    analysis -->|вызов анализа| claude
    api -->|import| core
    designer --> cli
    designer -->|пишет YAML| folder
    cli -->|import| core
    cli <-->|читает, пишет out/| folder
    cli -.->|project push / pull| db
```

LLM есть только в `service/analysis`; ядро не знает ни о сервисе, ни о сети, ни о базе
(контракты import-linter). Просмотр читает только `.epd`, из DXF ничего не считается обратно.

## Слои ядра

Пакеты `src/floorplan_engine/` лежат слоями: выше может импортировать ниже, не наоборот,
исключений нет (`uv run lint-imports`). Сантехника выше электрики: берёт её трассировку,
цены и развёртки.

```mermaid
flowchart TB
    cli["cli/ — команды, печать, коды выхода"]
    service["service/ — API, анализ (LLM), факты, база, очередь"]
    subgraph core["Ядро: без service, LLM, сети, базы и веба"]
        pipeline["pipeline/ — конвейер: сборка, оценка, сметы, цены, ответы, варианты"]
        epd["epd/ — артефакт просмотра .epd, отчёт, xlsx"]
        sheets["sheets/ — документ, раскладка листов, печать, PNG"]
        validation["validation/ — проверка модели, вопросы и их вес"]
        drawing["drawing/ — DXF через ezdxf"]
        plumbing["plumbing/ — сантехника: сеть, слабые места, смета"]
        electrical["electrical/ — расчёты электрики: трассы, коробки, щит, смета, монтаж"]
        model["model/ — схема YAML, intake, геометрия, масштаб, каталог щитов"]
    end
    cli --> service --> pipeline --> epd --> sheets --> validation --> drawing --> plumbing --> electrical --> model
```

`model/`, `validation/`, `electrical/` и `plumbing/` не импортируют ezdxf: модель, проверку и
расчёты можно гонять в тестах без чертежа. Общее для расчёта и рисования лежит ниже, в `model/`.

## Модель проекта

Пять файлов YAML в папке проекта, все ссылки между ними по `id`, а не по номеру: вставка стены
или точки ничего не ломает, а ответ на вопрос знает, в какое поле модели ему ложиться
(`target`). Пунктир — зависимость по ссылке или подстановка.

```mermaid
classDiagram
    class Plan {
        room.yaml
        rooms: id, lang, sheet
        walls: id, length, turn, thickness
        openings: wall, offset, width, hinge
        origin, scale
    }
    class Electrical {
        electrical.yaml
        points: id, type, wall, offset, height, group
        panel: type, phases, groups QF1…
        cables: from, to, group, brand, route
        led_strips: strip, supply
    }
    class Plumbing {
        plumbing.yaml
        risers: at от origin
        inlet: узел ввода
        fixtures: type, wall, offset, heights
        obstacles, distribution collector | tee
    }
    class Intake {
        intake.yaml
        sources: file, kind, note
        stages: что известно по этапам
        questions: id, weight, audience, target, assumption
    }
    class Answers {
        answers.yaml
        qN: число | choice | accept | text
        resolved, returned, comment
        log: кто, когда
    }
    class Studio {
        studio.yaml, prices.yaml
        организация, стадия, подписи
        прайс работ и материалов
    }
    Electrical ..> Plan : points.wall → walls.id
    Electrical ..> Electrical : cables.from, to → points.id
    Plumbing ..> Plan : fixtures.wall → walls.id
    Intake ..> Plan : target
    Intake ..> Electrical : target
    Intake ..> Plumbing : target
    Answers ..> Intake : qN → questions.id
    Studio ..> Plan : пустые графы sheet
```

`Plan`, `Electrical`, `Studio` — `model/schema.py`; `Plumbing` — `model/plumbing.py`; `Intake`,
`Answers` — `model/intake.py`. Рядом лежат `wiring.yaml` (ручные правки трасс) и `variant.yaml`
(вариант проводки из просмотра): модель они не меняют, их пишет не человек.

## Фронт web/

Самостоятельный проект: в Python нет ни HTML, ни статики. Стрелка — разрешённый импорт через
`@/` (`web/src/structure.test.ts`); внутри своей группы импорт разрешён всем, кроме `ui/`.

```mermaid
flowchart TB
    pages["pages/ — экраны: Viewer, Welcome, Gate, Studio"]
    widgets["widgets/ — блоки экрана: листы, карточки, окна, вход"]
    ui["ui/ — атомы без знания о проекте, у каждого сторис"]
    engine["engine/ — холсты вне React: sheet, panel, elevation, three"]
    shared["shared/ — store, types (.epd), api, auth, domains, mode, i18n, styles"]
    pages --> widgets & ui & engine & shared
    widgets --> ui & engine & shared
    ui --> shared
    engine --> shared
```

Холсты живут вне React: лист рисуется тысячами объектов и перерисовывается при каждом
движении. `shared/types.ts` описывает формат `.epd` и держится в согласии с
[epd-format.md](epd-format.md) руками. Админка `admin/` устроена так же, отдельным проектом.

## Состояния проекта в сервисе

`service/workflow.py`: анализ может кончиться вопросами, а не моделью; сборка детерминирована
и падает только на ошибке кода. Раундов вопросов не больше трёх (`MAX_ROUNDS`), потом проект
собирается по допущениям. Занятые состояния — `analyzing` и `building`: второй запуск в них
получает конфликт.

```mermaid
stateDiagram-v2
    [*] --> created : загружен source/
    created --> analyzing : анализ
    analyzing --> rejected : источник непригоден (gate), модель не вызывалась
    analyzing --> needs_model : модели нет, ошибки или текстовые ответы ждут разбора
    analyzing --> needs_answers : открытые вопросы, раунд не последний
    analyzing --> ready : собрано
    analyzing --> insufficient : план не строится, спросить нечего
    analyzing --> failed : ошибка кода
    needs_answers --> building : ответы
    building --> needs_model
    building --> needs_answers : новый раунд
    building --> ready
    building --> insufficient
    building --> failed : ошибка кода
    needs_model --> analyzing : исправленная модель, новый анализ
    rejected --> analyzing : другие источники
    ready --> [*]
```

В режиме базы новая версия модели (push, ответ или мастер в просмотре) пересобирает проект
`project_store.build`; это не меняет `ProjectState`, «сборка устарела» считается по дате YAML
и `answers_digest`.
