// Боковая панель листа: таблицы (связь строка ↔ объекты) и слои — у листов, нарисованных
// из примитивов (у щита слоёв нет: он рисуется своим компонентом). Вопросы, исходники
// и проект — в шапке (Drawer.tsx).

import { useEffect, useMemo, useState } from "react";
import { LAYER, SIDE, SHEET_ONLY, type SideTab } from "./consts";
import { expand } from "./page";
import { refreshPalette, screenColor } from "./palette";
import { useView, view } from "./store";
import type { Page, SideTable } from "./types";

interface Props {
  tab: SideTab;
  onTab: (tab: SideTab) => void;
  page: Page | null;
  children?: React.ReactNode;  // выдвижная панель шапки — поверх боковой
}

// Слои есть у листа, нарисованного из примитивов: у щита (page.panel) — нет
export const hasLayers = (page: Page | null) =>
  !!page && !page.panel && page.items.some((it) => !SHEET_ONLY.has(it.l));

export function SidePanel({ tab, onTab, page, children }: Props) {
  const tabs = (Object.keys(SIDE) as SideTab[]).filter((k) => k !== "layers" || hasLayers(page));
  const shown = tabs.includes(tab) ? tab : "tables";
  return (
    <aside>
      {tabs.length > 1 && (
        <div className="side-tabs" role="tablist">
          {tabs.map((k) => (
            <button key={k} role="tab" className={k === shown ? "on" : undefined} aria-selected={k === shown}
                    onClick={() => onTab(k)}>{SIDE[k]}</button>
          ))}
        </div>
      )}
      <div className="side-body">{shown === "layers" ? <Layers page={page} /> : <Tables page={page} />}</div>
      {children}
    </aside>
  );
}

// Таблицы листа: строка со ссылками на объекты подсвечивается при наведении на объект
// и сама подсвечивает их на чертеже
function Tables({ page }: { page: Page | null }) {
  const hover = useView((s) => s.hover);
  const [rowHover, setRowHover] = useState<string | null>(null);
  const hoverKeys = useMemo(() => new Set(hover ? expand(hover) : []), [hover]);

  // Объект под курсором на чертеже — прокрутить панель к его первой строке
  useEffect(() => {
    if (hover) document.querySelector(".side-body tr.lit")?.scrollIntoView({ block: "nearest" });
  }, [hover]);

  if (!page) return <div className="muted">Лист не открыт</div>;
  const tables = page.tables || [];
  if (!tables.length) return <div className="muted">В артефакте нет таблиц для панели — пересоберите проект (build)</div>;
  return (
    <>
      {tables.map((t, ti) => (
        <TableView key={ti} t={t} id={`${ti}`} rowHover={rowHover} hoverKeys={hoverKeys}
                   onRow={(rid, keys) => { setRowHover(rid); view.set({ lit: keys }); }}
                   onPick={page.panel ? (keys) => view.set({ pinned: keys[0] }) : undefined} />
      ))}
    </>
  );
}

// onPick — клик по строке (лист «Щит»: карточка аппарата)
function TableView({ t, id, rowHover, hoverKeys, onRow, onPick }: {
  t: SideTable; id: string; rowHover: string | null; hoverKeys: Set<string>;
  onRow: (rid: string | null, keys: Set<string> | null) => void;
  onPick?: (keys: string[]) => void;
}) {
  const al = (i: number) => (t.align[i] === "left" ? undefined : "c");
  return (
    <>
      <h3>{t.title}</h3>
      <table className="data">
        <thead><tr>{t.columns.map((c, i) => <th key={i} className={al(i)}>{c}</th>)}</tr></thead>
        <tbody>
          {t.rows.map((r, ri) => {
            const rid = `${id}/${ri}`;
            const lit = rid === rowHover || (!!r.keys && r.keys.some((k) => hoverKeys.has(k)));
            const cls = [r.section ? "section" : "", r.keys ? "linked" : "", lit ? "lit" : ""].join(" ").trim();
            return (
              <tr key={ri} className={cls || undefined}
                  onPointerEnter={r.keys ? () => onRow(rid, new Set(r.keys)) : undefined}
                  onPointerLeave={r.keys ? () => onRow(null, null) : undefined}
                  onClick={onPick && r.keys?.length ? () => onPick(r.keys!) : undefined}>
                {r.cells.map((c, i) => (
                  <td key={i} className={i === 0 && r.color ? "mark" : al(i)}>
                    {/* Группа щита — кружок её цвета, как линии на чертеже */}
                    {i === 0 && r.color && <span className="dot" style={{ background: r.color }} aria-hidden="true" />}
                    {c}
                  </td>
                ))}
              </tr>
            );
          })}
          {t.total && <tr className="total">{t.total.map((c, i) => <td key={i} className={al(i)}>{c}</td>)}</tr>}
        </tbody>
      </table>
      {t.notes && <ul className="notes">{t.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
    </>
  );
}

function Layers({ page }: { page: Page | null }) {
  const hidden = useView((s) => s.hidden);
  useView((s) => s.themeTick);
  if (!page) return <div className="muted">Лист не открыт</div>;
  refreshPalette();
  const colors = new Map<string, string>();
  for (const it of page.items) if (!SHEET_ONLY.has(it.l) && !colors.has(it.l)) colors.set(it.l, it.c);
  const toggle = (l: string, on: boolean) => {
    const next = new Set(hidden);
    if (on) next.delete(l); else next.add(l);
    view.set({ hidden: next });
  };
  return (
    <div className="layers">
      {[...colors.keys()].sort().map((l) => (
        <label key={l} htmlFor={`layer-${l}`}>
          <input type="checkbox" id={`layer-${l}`} checked={!hidden.has(l)}
                 onChange={(e) => toggle(l, e.target.checked)} />
          <span aria-hidden="true" style={{ width: 14, height: 4, flex: "none", background: screenColor(colors.get(l)!) }} />
          {LAYER[l] || l}
          <span className="code mono">{l}</span>
        </label>
      ))}
    </div>
  );
}
