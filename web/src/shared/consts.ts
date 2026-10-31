// Ключи вкладок и режимов и параметры показа

// Подписи — в словарях i18n (src/i18n): здесь только ключи
export const SIDE_TABS = ["tables", "layers"] as const;
export type SideTab = (typeof SIDE_TABS)[number];
// Не про лист — кнопками в шапке, выдвижной панелью (widgets/Drawer)
export const DRAWER_TABS = ["questions", "sources", "project"] as const;
export type DrawerTab = (typeof DRAWER_TABS)[number];
export const THEMES = ["system", "light", "dark"] as const;
export type Theme = (typeof THEMES)[number];

// PNG листа для альбома: не больше A3 при 150 dpi
export const PNG_DPI = 150, PNG_LONG = 2480, PNG_SHORT = 1754;
export const MIN_LINE_PX = 0.6;  // тоньше на экране линия не рисуется
export const CABLE_MIN_PX = 2;   // линии проводки на экране не тоньше (на листе 0,25 мм — меньше 1 px)
// Слои только листа DXF (рамка, штамп, таблицы): на экране их нет, в PNG для альбома — есть
export const SHEET_ONLY = new Set(["A-SHEET", "A-VPORT"]);
export const VIEW_PAD = 16;
export const FIT_SHRINK = 0.93;     // «весь чертёж» на 7 % мельче впритык — подписи снизу не обрезаются
export const TIP_GAP = 12;          // px от закреплённой подсказки до края и до чертежа
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
export const WALL_MODES = ["cut", "ghost", "none"] as const;
export type WallMode = (typeof WALL_MODES)[number];

export const REDUCED_MOTION = typeof window !== "undefined"
  && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
