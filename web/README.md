# shtroba-web — просмотр проектов

Фронт просмотра собранных проектов Штроба: листы `.epd` в canvas, таблицы и подсказки,
правка трасс проводки, 3D проводки. React 18 + TypeScript + Vite; 3D — react-three-fiber.

Данные — API бэка (`shtroba view`, порт 8000). Запросы `/api` идут к нему через прокси
Vite, поэтому CORS не нужен.

## Запуск

```bash
# 1. API (из корня репозитория)
uv run shtroba view                 # http://127.0.0.1:8000/api

# 2. Фронт (из web/)
npm install
npm run dev                             # http://127.0.0.1:5173 — с перезагрузкой при правках
```

API на другом адресе — переменная `API_URL`: `API_URL=http://127.0.0.1:8765 npm run dev`.

## Команды

| Команда | Что делает |
| --- | --- |
| `npm run dev` | сервер разработки, порт 5173 |
| `npm run build` | проверка типов и сборка в `dist/` |
| `npm run preview` | собранный `dist/` на порту 4173 (с тем же прокси к API) |
| `npm run check` | типы TypeScript |
| `npm test` | тесты (vitest) |

## Выкладка

`dist/` — обычная статика: её отдаёт любой веб-сервер, а `/api` он проксирует на бэк.
Пример nginx:

```nginx
location /api/ { proxy_pass http://127.0.0.1:8000; }
location / { root /srv/shtroba-web/dist; try_files $uri /index.html; }
```

## Устройство

| Файл | Что |
| --- | --- |
| `src/App.tsx` | проект из адреса (`#имя`), листы, шапка |
| `src/SheetStage.tsx` | область чертежа: лист или 3D, кнопки под ним |
| `src/SidePanel.tsx` | боковая панель: таблицы, слои, вопросы, исходники, проект |
| `src/Tip.tsx`, `src/SourceView.tsx` | подсказка объекта; исходник на месте листа |
| `src/sheet/SheetView.ts` | рисование листа в canvas (вне React), масштаб, выделение |
| `src/edit/` | правка трасс; `geometry.ts` — чистые функции с тестами |
| `src/three/Scene3D.tsx` | 3D проводки; отдельный файл, грузится по кнопке «3D» |
| `src/store.ts` | общее состояние: под курсором, выделение, слои, режимы |
| `src/types.ts` | типы API и формата `.epd` — держать в согласии с `docs/epd-format.md` |
