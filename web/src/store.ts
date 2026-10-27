// Общее состояние показа листа: что под курсором, что выделено, подсказка, слои, режимы.
// Его читают и лист (canvas, вне React), и 3D, и боковая панель — поэтому не React-состояние,
// а маленькое хранилище с подпиской (useView).

import { useSyncExternalStore } from "react";
import type { WallMode } from "./consts";

export interface Tip {
  key: string;
  x: number;  // px от левого верхнего угла области чертежа
  y: number;
}

export interface ViewState {
  hover: string | null;             // объект под курсором (лист или 3D)
  lit: Set<string> | null;          // объекты строки таблицы под курсором
  selected: Set<string> | null;     // выделенная линия целиком
  neighbors: Set<string> | null;    // остальное той же группы QF
  tip: Tip | null;                  // подсказка у курсора
  pinned: string | null;            // закреплённая подсказка (по клику) — у объекта
  hidden: Set<string>;              // выключенные слои — общие для всех листов
  editMode: boolean;                // «Править трассы»
  show3d: boolean;                  // лист проводки — в 3D
  wallMode: WallMode;
  themeTick: number;                // сменилась тема — перекрасить
}

type Listener = () => void;

let state: ViewState = {
  hover: null, lit: null, selected: null, neighbors: null, tip: null, pinned: null,
  hidden: new Set(), editMode: false, show3d: false, wallMode: "cut", themeTick: 0,
};
const listeners = new Set<Listener>();

export const view = {
  get: () => state,
  set(patch: Partial<ViewState>) {
    state = { ...state, ...patch };
    for (const l of listeners) l();
  },
  subscribe(l: Listener) {
    listeners.add(l);
    return () => { listeners.delete(l); };
  },
};

export function useView<T>(pick: (s: ViewState) => T): T {
  return useSyncExternalStore(view.subscribe, () => pick(state));
}

// Новый лист — без выделения и подсказки
export function resetSelection() {
  view.set({ hover: null, lit: null, selected: null, neighbors: null, tip: null, pinned: null });
}
