// Боковая панель листа: таблицы (связь строка ↔ объекты) и слои — у листов, нарисованных
// из примитивов (у щита слоёв нет: он рисуется своим компонентом). Слои — свои слои листа
// и слои с других листов общего чертежа (sheet/drawing.ts). Вопросы, исходники и проект —
// в шапке (Drawer.tsx). У вкладки «Электрика» сверху — вид: точки, освещение, проводка (листы
// одного чертежа); вид меняет слои, таблицы, подсказки и правку, масштаб остаётся.
// Узкий экран: панель — нижняя шторка: полоса с видом и «▴» внизу, таблицы и слои — по ней.

import { useEffect, useMemo, useState } from "react";
import { LAYER, SIDE, SHEET_ONLY, type SideTab } from "./consts";
import { cx } from "./cx";
import { expand } from "./page";
import { refreshPalette, screenColor } from "./palette";
import { drawingLayers, layerShown, type Drawing } from "./sheet/drawing";
import { useView, view } from "./store";
import css from "./SidePanel.module.scss";
import ui from "./styles/ui.module.scss";
import type { Page, SideTable } from "./types";

interface Props {
  tab: SideTab;
  onTab: (tab: SideTab) => void;
  page: Page | null;
  drawing: Drawing | null;     // чертёж, на котором стоит лист
  views?: { index: number; label: string }[] | null;  // виды вкладки (tabs.ts)
  view?: number | null;
  onView?: (index: number) => void;
  children?: React.ReactNode;  // выдвижная панель шапки — поверх боковой
}

// Слои есть у листа, нарисованного из примитивов: у щита (page.panel) — нет
export const hasLayers = (page: Page | null) =>
  !!page && !page.panel && page.items.some((it) => !SHEET_ONLY.has(it.l));

export function SidePanel({ tab, onTab, page, drawing, views, view: current, onView, children }: Props) {
  const tabs = (Object.keys(SIDE) as SideTab[]).filter((k) => k !== "layers" || hasLayers(page));
  const shown = tabs.includes(tab) ? tab : "tables";
  const [open, setOpen] = useState(false);  // узкий экран: шторка развёрнута
  const hasViews = !!views && views.length > 1;
  return (
    <aside className={css.side} data-open={open || undefined}>
      <div className={cx(css.bar, !hasViews && css.barEmpty)}>
        {hasViews ? (
          <div className={ui.segmented} role="radiogroup" aria-label="Вид чертежа">
            {views!.map((v) => (
              <button key={v.index} role="radio" aria-checked={v.index === current}
                      className={cx(v.index === current && ui.on)} onClick={() => onView?.(v.index)}>{v.label}</button>
            ))}
          </div>
        ) : <span className={css.title}>{tabs.length > 1 ? "Таблицы и слои" : SIDE[shown]}</span>}
        <button className={css.toggle} aria-expanded={open} aria-label={open ? "Свернуть" : "Таблицы и слои"}
                onClick={() => setOpen(!open)}>{open ? "▾" : "▴"}</button>
      </div>
      {tabs.length > 1 && (
        <div className={css.tabs} role="tablist">
          {tabs.map((k) => (
            <button key={k} role="tab" aria-selected={k === shown}
                    onClick={() => onTab(k)}>{SIDE[k]}</button>
          ))}
        </div>
      )}
      <div className={cx(ui.panelBody, css.body)}>{shown === "layers" ? <Layers page={page} drawing={drawing} /> : <Tables page={page} />}</div>
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
    if (hover) document.querySelector(`.${css.side} tr.${css.lit}`)?.scrollIntoView({ block: "nearest" });
  }, [hover]);

  if (!page) return <div className="muted">Лист не открыт</div>;
  const tables = page.tables || [];
  if (!tables.length) return <div className="muted">У этого листа таблиц нет</div>;
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
  const al = (i: number) => (t.align[i] === "left" ? undefined : css.c);
  return (
    <>
      <h3>{t.title}</h3>
      <table className={css.table}>
        <thead><tr>{t.columns.map((c, i) => <th key={i} className={al(i)}>{c}</th>)}</tr></thead>
        <tbody>
          {t.rows.map((r, ri) => {
            const rid = `${id}/${ri}`;
            const lit = rid === rowHover || (!!r.keys && r.keys.some((k) => hoverKeys.has(k)));
            return (
              <tr key={ri} className={cx(r.section && css.section, r.keys && css.linked, lit && css.lit)}
                  onPointerEnter={r.keys ? () => onRow(rid, new Set(r.keys)) : undefined}
                  onPointerLeave={r.keys ? () => onRow(null, null) : undefined}
                  onClick={onPick && r.keys?.length ? () => onPick(r.keys!) : undefined}>
                {r.cells.map((c, i) => (
                  <td key={i} className={i === 0 && r.color ? css.mark : al(i)}>
                    {/* Группа щита — кружок её цвета, как линии на чертеже */}
                    {i === 0 && r.color && <span className={ui.dot} style={{ background: r.color }} aria-hidden="true" />}
                    {c}
                  </td>
                ))}
              </tr>
            );
          })}
          {t.total && <tr className={css.total}>{t.total.map((c, i) => <td key={i} className={al(i)}>{c}</td>)}</tr>}
        </tbody>
      </table>
      {t.notes && <ul className={css.notes}>{t.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
    </>
  );
}

function Layers({ page, drawing }: { page: Page | null; drawing: Drawing | null }) {
  const { hidden, extra } = useView((s) => s);
  useView((s) => s.themeTick);
  if (!page || !drawing) return <div className="muted">Лист не открыт</div>;
  refreshPalette();
  const colors = drawingLayers(drawing);
  const own = drawing.own.get(page) ?? new Set(colors.keys());
  // Свой слой — выключить на всех листах; с другого листа — добавить на чертёж
  const toggle = (l: string, on: boolean) => {
    const set = new Set(own.has(l) ? hidden : extra);
    if (own.has(l) === on) set.delete(l); else set.add(l);
    view.set(own.has(l) ? { hidden: set } : { extra: set });
  };
  const row = (l: string) => (
    <label key={l} htmlFor={`layer-${l}`}>
      <input type="checkbox" id={`layer-${l}`} checked={layerShown(own, hidden, extra, l)}
             onChange={(e) => toggle(l, e.target.checked)} />
      <span className={css.swatch} aria-hidden="true" style={{ background: screenColor(colors.get(l)!) }} />
      {LAYER[l] || l}
      <span className={cx(css.code, "mono")}>{l}</span>
    </label>
  );
  const mine = [...colors.keys()].filter((l) => own.has(l)).sort();
  const rest = [...colors.keys()].filter((l) => !own.has(l)).sort();
  return (
    <div className={css.layers}>
      {rest.length > 0 && <h3>Слои вида</h3>}
      {mine.map(row)}
      {rest.length > 0 && (
        <>
          <h3>Другие слои</h3>
          <p className="small muted">Добавить на чертёж: размеры к проводке, номера точек к освещению — из других видов и плана.</p>
          {rest.map(row)}
        </>
      )}
    </div>
  );
}
