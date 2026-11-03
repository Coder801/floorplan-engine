// Sheet side panel: tables (row ↔ objects link) and layers, for sheets drawn from primitives
// (the panel has no layers: it is drawn by its own component). Layers are the sheet's own layers
// and layers from other sheets of the shared drawing (sheet/drawing.ts). Questions, sources and
// the project are in the header (widgets/Drawer). The "Electrical" tab has a view on top:
// points, lighting, wiring (sheets of one drawing); the view changes layers, tables, hints and
// editing, the zoom stays.
// Narrow screen: the panel is a bottom drawer: a strip with the view and "▴" at the bottom,
// tables and layers inside it.

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { drawingLayers, layerShown, type Drawing } from "@/engine/sheet/drawing";
import { SHEET_ONLY, SIDE_TABS, type SideTab } from "@/shared/consts";
import { cx } from "@/shared/cx";
import { label } from "@/shared/i18n";
import { rowKind, totals } from "@/shared/estimate";
import { expand } from "@/shared/page";
import { refreshPalette, screenColor } from "@/shared/palette";
import { useView, view } from "@/shared/store";
import ui from "@/shared/styles/ui.module.scss";
import type { Elevation, Page, SideTable } from "@/shared/types";
import { EyeToggle } from "@/ui/EyeToggle";
import { WallItems } from "@/widgets/WallItems";
import css from "./SidePanel.module.scss";

interface Props {
  tab: SideTab;
  onTab: (tab: SideTab) => void;
  page: Page | null;
  drawing: Drawing | null;     // the drawing the sheet belongs to
  views?: { index: number; label: string }[] | null;  // tab views (tabs.ts)
  view?: number | null;
  onView?: (index: number) => void;
  wall?: Elevation | null;      // elevation: what is on the wall, instead of tables and layers
  estimate?: SideTable | null;  // "Estimate" tab: totals and notes instead of tables and layers
  onWiring?: (key: string) => void;  // from an elevation to the wiring sheet, to the object's line
  // Wiring variant as a line above the tables of the "Electrical" views and "Estimate"; the
  // choice is on the "Overview" tab (onOpen)
  variant?: { label: string; onOpen: () => void } | null;
  summary?: React.ReactNode;    // "Overview" tab: totals instead of tables and layers
  children?: React.ReactNode;  // the header slide-out panel, on top of the side panel
}

// The wiring variant changes groups, panel and routes: the line shows on every "Electrical" view and in "Estimate"
const VARIANT_STAGES = new Set(["electrical", "lighting", "wiring"]);

// Layers exist for a sheet drawn from primitives; the panel (page.panel) has none
export const hasLayers = (page: Page | null) =>
  !!page && !page.panel && page.items.some((it) => !SHEET_ONLY.has(it.l));

export function SidePanel({ tab, onTab, page, drawing, views, view: current, onView, wall, estimate, onWiring, variant, summary, children }: Props) {
  const { t } = useTranslation();
  const tabs: SideTab[] = wall || estimate || summary ? [] : SIDE_TABS.filter((k) => k !== "layers" || hasLayers(page));
  const shown = tabs.includes(tab) ? tab : "tables";
  const [open, setOpen] = useState(false);  // narrow screen: the drawer is expanded
  const hasViews = !estimate && !summary && !!views && views.length > 1;
  return (
    <aside className={css.side} data-open={open || undefined}>
      <div className={cx(css.bar, !hasViews && css.barEmpty)}>
        {hasViews ? (
          <div className={ui.segmented} role="radiogroup" aria-label={t("side.view")}>
            {views!.map((v) => (
              <button key={v.index} role="radio" aria-checked={v.index === current}
                      className={cx(v.index === current && ui.on)} onClick={() => onView?.(v.index)}>{v.label}</button>
            ))}
          </div>
        ) : <span className={css.title}>{wall ? t("side.onWall") : summary ? t("overview.side") : estimate ? t("estimate.totals") : tabs.length > 1 ? t("side.tablesAndLayers") : t(`side.${shown}`)}</span>}
        <button className={css.toggle} aria-expanded={open} aria-label={open ? t("side.collapse") : t("side.tablesAndLayers")}
                onClick={() => setOpen(!open)}>{open ? "▾" : "▴"}</button>
      </div>
      {tabs.length > 1 && (
        <div className={css.tabs} role="tablist">
          {tabs.map((k) => (
            <button key={k} role="tab" aria-selected={k === shown}
                    onClick={() => onTab(k)}>{t(`side.${k}`)}</button>
          ))}
        </div>
      )}
      <div className={cx(ui.panelBody, css.body)}>
        {!wall && !summary && variant && (estimate || (VARIANT_STAGES.has(page?.stage ?? "") && shown === "tables")) && (
          <p className={css.variant}>
            <span className="muted">{t("variant.current")}</span> {variant.label}
            <button className={css.change} onClick={variant.onOpen}>{t("variant.change")}</button>
          </p>
        )}
        {summary ? summary
          : wall ? <WallItems wall={wall} onWiring={onWiring} />
          : estimate ? <EstimateTotals table={estimate} />
          : shown === "layers" ? <Layers page={page} drawing={drawing} /> : <Tables page={page} />}
      </div>
      {children}
    </aside>
  );
}

// Sheet tables: a row linked to objects lights up when an object is hovered and highlights
// them on the drawing itself
function Tables({ page }: { page: Page | null }) {
  const { t } = useTranslation();
  const hover = useView((s) => s.hover);
  const [rowHover, setRowHover] = useState<string | null>(null);
  const hoverKeys = useMemo(() => new Set(hover ? expand(hover) : []), [hover]);

  // Object under the cursor on the drawing: scroll the panel to its first row
  useEffect(() => {
    if (hover) document.querySelector(`.${css.side} tr.${css.lit}`)?.scrollIntoView({ block: "nearest" });
  }, [hover]);

  if (!page) return <div className="muted">{t("side.noSheet")}</div>;
  const tables = page.tables || [];
  if (!tables.length) return <div className="muted">{t("side.noTables")}</div>;
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

// onPick is a row click ("Panel" sheet: the device card)
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
                  <td key={i} className={i === 0 && (r.color || r.marker) ? css.mark : al(i)}>
                    {/* A panel group gets a dot in its colour, like the lines on the drawing; a device not on a
                        line (main switch, relay, backup, battery box) gets a square */}
                    {i === 0 && r.color && <span className={ui.dot} style={{ background: r.color }} aria-hidden="true" />}
                    {i === 0 && !r.color && r.marker === "square" && <span className={ui.square} aria-hidden="true" />}
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

// "Estimate" tab: section totals and "Total"; without prices, the item count; calculation notes
function EstimateTotals({ table }: { table: SideTable }) {
  const { t } = useTranslation();
  const sums = totals(table.rows, table.total);
  const items = table.rows.filter((r) => rowKind(r) === "line").length;
  return (
    <>
      <dl className={css.totals}>
        {sums.length
          ? sums.map(([name, value], i) => [<dt key={`n${i}`}>{name}</dt>, <dd key={`v${i}`}>{value}</dd>])
          : [<dt key="n">{t("estimate.items")}</dt>, <dd key="v">{items}</dd>]}
      </dl>
      {!!table.notes?.length && <ul className={css.notes}>{table.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
    </>
  );
}

function Layers({ page, drawing }: { page: Page | null; drawing: Drawing | null }) {
  const { t } = useTranslation();
  const { hidden, extra } = useView((s) => s);
  useView((s) => s.themeTick);
  if (!page || !drawing) return <div className="muted">{t("side.noSheet")}</div>;
  refreshPalette();
  const colors = drawingLayers(drawing);
  const own = drawing.own.get(page) ?? new Set(colors.keys());
  // Own layer: switch it off on all sheets; from another sheet: add it to the drawing
  const toggle = (l: string, on: boolean) => {
    const set = new Set(own.has(l) ? hidden : extra);
    if (own.has(l) === on) set.delete(l); else set.add(l);
    view.set(own.has(l) ? { hidden: set } : { extra: set });
  };
  // Layer row: eye (as in Photoshop) | colour | name | code; a click on the row works too
  const row = (l: string) => {
    const shown = layerShown(own, hidden, extra, l);
    return (
      <div key={l} className={cx(css.layer, !shown && css.hiddenLayer)} onClick={() => toggle(l, !shown)}>
        <EyeToggle on={shown} what={label("layer", l)} onToggle={() => toggle(l, !shown)} />
        <span className={css.swatch} aria-hidden="true" style={{ background: screenColor(colors.get(l)!) }} />
        {label("layer", l)}
        <span className={cx(css.code, "mono")}>{l}</span>
      </div>
    );
  };
  const mine = [...colors.keys()].filter((l) => own.has(l)).sort();
  const rest = [...colors.keys()].filter((l) => !own.has(l)).sort();
  return (
    <div className={css.layers}>
      {rest.length > 0 && <h3>{t("side.ownLayers")}</h3>}
      {mine.map(row)}
      {rest.length > 0 && (
        <>
          <h3>{t("side.otherLayers")}</h3>
          <p className="small muted">{t("side.otherNote")}</p>
          {rest.map(row)}
        </>
      )}
    </div>
  );
}
