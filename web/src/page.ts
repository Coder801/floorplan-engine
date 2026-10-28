// Связи объектов страницы: линия целиком (chains), группа (groups), карточки (objects)

import { OBJECT } from "./consts";
import type { ObjectCard, Page } from "./types";

// Ключи объекта для сверки с таблицами: общая подпись точек — это её точки
export const expand = (o: string): string[] =>
  (o.startsWith("label:") ? o.slice(6).split(",").map((id) => `point:${id}`) : [o]);

// other — карточки других листов общего чертежа: для объектов слоя, включённого с чужого
// листа (размеры на проводке); свои карточки и линии листа главнее
export class PageIndex {
  readonly objects: Record<string, ObjectCard> | null;
  readonly chains: Record<string, string[]>;
  readonly groupOf = new Map<string, Set<string>>();

  constructor(page: Page, private readonly other: Record<string, ObjectCard> = {}) {
    this.objects = page.objects || null;
    this.chains = page.chains || {};
    for (const keys of Object.values(page.groups || {})) {
      const all = new Set(keys);
      for (const k of keys) this.groupOf.set(k, all);
    }
  }

  // Линия объекта для выделения; подпись нескольких точек — линии всех её точек
  chainOf(o: string): Set<string> {
    const keys = expand(o).flatMap((k) => this.chains[k] || [k]);
    return new Set([o, ...keys]);
  }

  // Соседи — остальное той же группы QF (её другие коробки, ветки и точки)
  neighborsOf(chain: Set<string>): Set<string> | null {
    for (const k of chain) {
      const g = this.groupOf.get(k);
      if (g) return g;
    }
    return null;
  }

  interactive(o: string | null | undefined): o is string {
    return !!o && (!this.objects || o in this.objects || expand(o).some((k) => k in this.chains) || o in this.other);
  }

  // Карточка объекта; точка на листе проводки — карточка линии до неё; нет — тип и id
  card(o: string): ObjectCard {
    const objs = this.objects || {};
    const info = objs[o] || objs[(this.chains[o] || [])[0]] || this.other[o];
    if (info) return info;
    const i = o.indexOf(":");
    return { title: `${OBJECT[o.slice(0, i)] || o.slice(0, i)} · ${o.slice(i + 1)}`, rows: [] };
  }
}
