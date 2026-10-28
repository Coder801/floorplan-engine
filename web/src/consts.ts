// Подписи интерфейса и параметры показа

export const STATUS: Record<string, string> = {
  ready: "строится", questions: "есть вопросы", insufficient: "мало данных",
  invalid: "ошибки в модели", blocked: "заблокирован", absent: "нет данных",
  unsupported: "не поддерживается",
};
export const STAGE: Record<string, string> = {
  plan: "План", electrical: "Электрика", wiring: "Проводка", plumbing: "Сантехника",
  furniture: "Мебель", lighting: "Освещение", panel: "Щит",
};
export const QSTATE: Record<string, string> = {
  open: "открыт", answered: "ответ подставлен", accepted: "оставлено допущение",
  text: "текст ждёт разбора",
};
export const SEVERITY: Record<string, string> = { critical: "критично", major: "важно", minor: "уточнение" };
export const LAYER: Record<string, string> = {
  "A-WALL": "стены", "A-DOOR": "двери", "A-WIND": "окна", "A-DIMS": "размеры",
  "A-TEXT": "подписи плана", "A-SHEET": "рамка и штамп", "E-SOCKET": "розетки",
  "E-SWITCH": "выключатели", "E-LIGHT": "свет", "E-DATA": "слаботочка", "E-LED": "LED",
  "E-BOARD": "щит", "E-TEXT": "подписи электрики", "W-BOX": "коробки", "W-CABLE": "кабели",
  "W-CABLE-FLOOR": "кабели по полу", "W-TEXT": "подписи проводки", "E-LINK": "связи света",
  "L-TEXT": "номера света", "0": "прочее",
};
export const OBJECT: Record<string, string> = {
  room: "Помещение", wall: "Стена", dimension: "Размеры стены", opening: "Проём",
  point: "Точка", label: "Подпись точек", board: "Щит", cable: "Кабель", led_strip: "LED-лента",
  wire: "Линия проводки", box: "Коробка",
};
export const SIDE = { tables: "Таблицы", layers: "Слои" } as const;
export type SideTab = keyof typeof SIDE;
// Не про лист — кнопками в шапке, выдвижной панелью (Drawer.tsx)
export const DRAWER = { questions: "Вопросы", sources: "Исходники", project: "Проект" } as const;
export type DrawerTab = keyof typeof DRAWER;
export const THEMES = ["system", "light", "dark"] as const;
export type Theme = (typeof THEMES)[number];
export const THEME_NAME: Record<Theme, string> = {
  system: "Тема: авто", light: "Тема: светлая", dark: "Тема: тёмная",
};

// PNG листа для альбома: не больше A3 при 150 dpi
export const PNG_DPI = 150, PNG_LONG = 2480, PNG_SHORT = 1754;
export const MIN_LINE_PX = 0.6;  // тоньше на экране линия не рисуется
export const CABLE_MIN_PX = 2;   // линии проводки на экране не тоньше (на листе 0,25 мм — меньше 1 px)
// Слои только листа DXF (рамка, штамп, таблицы): на экране их нет, в PNG для альбома — есть
export const SHEET_ONLY = new Set(["A-SHEET", "A-VPORT"]);
export const VIEW_PAD = 16;
export const FIT_SHRINK = 0.93;     // «весь чертёж» на 7 % мельче впритык — подписи снизу не обрезаются
export const TIP_GAP = 12;          // px от закреплённой подсказки до края и до чертежа
export const FOCUS_MAX = 6;         // выделенная линия — не крупнее, чем 6× «весь чертёж»
export const FOCUS_MS = 280;        // длительность наезда на линию
export const NEIGHBOR_ALPHA = 0.75; // соседи выделенной линии по группе
export const DIM_ALPHA = 0.12;      // остальная проводка при выделении

// Правка трасс на листе проводки (ключ edit страницы): сдвиг — шагом SNAP_MM мм модели
export const SNAP_MM = 10;
export const EDIT_HIT_PX = 6;       // px от курсора до участка линии или коробки
export const EDIT_MOVE_PX = 3;      // сдвиг меньше — это клик, а не перетаскивание
// Правящаяся линия — бегущий пунктир от источника к цели (px экрана, px в секунду)
export const FLOW_WIDTH_PX = 4, FLOW_DASH_PX = 10, FLOW_GAP_PX = 7, FLOW_SPEED_PX = 32;

// 3D проводки
export const CUT_HEIGHT_MM = 300;   // ближние стены в срезе — бортиком такой высоты
export const CUT_DOT = 0.2;         // стена ближняя, если её помещение лежит дальше от камеры
export const WIRE_PX = 3, WIRE_SEL_PX = 4.5, WIRE_LIT_PX = 5;
export const GHOST_ALPHA = 0.3;     // часть линии, закрытая стеной, — бледно, но видна
export const WALL_ALPHA = 0.55, WALL_GHOST_ALPHA = 0.15;
export const WALL_MODES = [["cut", "Срез"], ["ghost", "Прозрачные"], ["none", "Без стен"]] as const;
export type WallMode = (typeof WALL_MODES)[number][0];

export const REDUCED_MOTION = typeof window !== "undefined"
  && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
