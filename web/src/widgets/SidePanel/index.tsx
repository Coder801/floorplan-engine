// Sheet side panel: tables (row ↔ objects link, group rows with an eye and a held tooltip) and layers, for sheets drawn from primitives
// (the panel has no layers: it is drawn by its own component). Layers are the sheet's own layers
// and layers from other sheets of the shared drawing (sheet/drawing.ts). Questions, sources and
// the project are in the header (widgets/Drawer). The "Electrical" tab has a view on top:
// points, lighting, wiring (sheets of one drawing); the view changes layers, tables, hints and
// editing, the zoom stays.
// Narrow screen: the panel is a bottom drawer: a strip with the view and "▴" at the bottom,
// tables and layers inside it.

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { CABLE_ROWS, drawingLayers, layerRows, objectLayers, type Drawing } from "@/engine/sheet/drawing";
import { ownLayers, viewTables } from "@/engine/sheet/views";
import { SHEET_ONLY, SIDE_TABS, type SideTab } from "@/shared/consts";
import { cx } from "@/shared/cx";
import { label } from "@/shared/i18n";
import { rowKind, totals } from "@/shared/estimate";
import { expand, rowPicked, rowSelection } from "@/shared/page";
import { refreshPalette, screenColor } from "@/shared/palette";
import { toggledGroups, useView, view } from "@/shared/store";
import ui from "@/shared/styles/ui.module.scss";
import type { TabView } from "@/shared/tabs";
import type { Elevation, Page, SideTable } from "@/shared/types";
import { EyeToggle } from "@/ui/EyeToggle";
import { useHoldTip } from "@/ui/HoldTip";
import { WallItems } from "@/widgets/WallItems";
import css from "./SidePanel.module.scss";

interface Props {
  tab: SideTab;
  onTab: (tab: SideTab) => void;
  page: Page | null;
  drawing: Drawing | null;     // the drawing the sheet belongs to
  views?: TabView[] | null;     // tab views (tabs.ts)
  view?: string | null;
  onView?: (view: TabView) => void;
  wall?: Elevation | null;      // elevation: what is on the wall, instead of tables and layers
  estimate?: SideTable | null;  // "Estimate" tab: totals and notes instead of tables and layers
  onWiring?: (key: string) => void;  // from an elevation to the wiring sheet, to the object's line
  // Wiring variant as a line above the tables of the "Electrical" views and "Estimate"; the
  // choice is on the "Overview" tab (onOpen)
  variant?: { label: string; onOpen: () => void } | null;
  summary?: React.ReactNode;    // "Overview" and "Tasks" tabs: their own content instead of tables and layers
  summaryTitle?: string;        // the strip title for summary ("Overview" by default)
  layers?: boolean;             // the "Layers" tab (the simple interface mode has only tables)
  children?: React.ReactNode;  // the header slide-out panel, on top of the side panel
}

// The wiring variant changes groups, panel and routes: the line shows on every "Electrical" view and in "Estimate"
const VARIANT_STAGES = new Set(["electrical", "lighting", "wiring"]);

// Layers exist for a sheet drawn from primitives; the panel (page.panel) has none
export const hasLayers = (page: Page | null) =>
  !!page && !page.panel && page.items.some((it) => !SHEET_ONLY.has(it.l));

export function SidePanel({ tab, onTab, page, drawing, views, view: current, onView, wall, estimate, onWiring, variant, summary, summaryTitle, layers = true, children }: Props) {
  const { t } = useTranslation();
  const tabs: SideTab[] = wall || estimate || summary ? [] : SIDE_TABS.filter((k) => k !== "layers" || (layers && hasLayers(page)));
  const shown = tabs.includes(tab) ? tab : "tables";
  const [open, setOpen] = useState(false);  // narrow screen: the drawer is expanded
  const hasViews = !estimate && !summary && !!views && views.length > 1;
  return (
    <aside className={css.side} data-open={open || undefined}>
      <div className={cx(css.bar, !hasViews && css.barEmpty)}>
        {hasViews ? (
          <div className={ui.segmented} role="radiogroup" aria-label={t("side.view")}>
            {views!.map((v) => (
              <button key={v.key} role="radio" aria-checked={v.key === current}
                      className={cx(v.key === current && ui.on)} onClick={() => onView?.(v)}>{v.label}</button>
            ))}
          </div>
        ) : <span className={css.title}>{wall ? t("side.onWall") : summary ? (summaryTitle ?? t("overview.side")) : estimate ? t("estimate.totals") : tabs.length > 1 ? t("side.tablesAndLayers") : t(`side.${shown}`)}</span>}
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
          : shown === "layers" ? <Layers page={page} drawing={drawing} /> : <Tables page={page} drawing={drawing} />}
      </div>
      {children}
    </aside>
  );
}

// Sheet tables: a row linked to objects lights up when an object is hovered and highlights
// them on the drawing itself
function Tables({ page, drawing }: { page: Page | null; drawing: Drawing | null }) {
  const { t } = useTranslation();
  const electricalView = useView((s) => s.electricalView);
  const cables = useView((s) => s.cables);
  const systemsOff = useView((s) => s.systemsOff);
  const hover = useView((s) => s.hover);
  const filter = useView((s) => s.filter3d);
  const selected = useView((s) => s.selected);
  const [rowHover, setRowHover] = useState<string | null>(null);
  const hoverKeys = useMemo(() => new Set(hover ? expand(hover) : []), [hover]);

  // Object under the cursor on the drawing: scroll the panel to its first row
  useEffect(() => {
    if (hover) document.querySelector(`.${css.side} tr.${css.lit}`)?.scrollIntoView({ block: "nearest" });
  }, [hover]);
  // A line selected on the drawing: scroll to its row too
  useEffect(() => {
    if (selected) document.querySelector(`.${css.side} tr.${css.lit}`)?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  if (!page) return <div className="muted">{t("side.noSheet")}</div>;
  // The simple interface mode: the routes without the group table (breakers, cables, kW)
  if (!cables && page.stage === "wiring") return <p className="muted">{t("side.wiringBrief")}</p>;
  // The electrical views and the wiring view without a system: rows of the objects shown
  const filtered = page.stage === "electrical" || (page.stage === "wiring" && systemsOff.size > 0);
  const tables = filtered && drawing
    ? viewTables(page.tables || [], ownLayers(drawing, page, electricalView, cables, systemsOff), objectLayers(drawing))
    : page.tables || [];
  if (!tables.length) return <div className="muted">{t("side.noTables")}</div>;
  // The eye of a group: every group of the sheet counts, also one with no table row
  const groups = [...new Set([...Object.keys(page.groups ?? {}), ...tables.flatMap((x) => x.rows.flatMap((r) => r.group ?? []))])];
  const toggle = (g: string) => view.set({
    filter3d: { ...filter, groups: toggledGroups(filter.groups, groups, g) },
    selected: null, neighbors: null, pinned: null, tip: null,
  });
  return (
    <>
      {tables.map((t, ti) => (
        <TableView key={ti} t={t} id={`${ti}`} rowHover={rowHover} hoverKeys={hoverKeys}
                   shown={filter.groups} onGroup={toggle} selected={selected}
                   onRow={(rid, keys) => { setRowHover(rid); view.set({ lit: keys }); }}
                   onPick={page.panel ? (keys) => view.set({ pinned: keys[0] })
                     : (keys) => view.set({ selected: rowSelection(selected, keys, page.chains), neighbors: null, pinned: null, tip: null })} />
      ))}
    </>
  );
}

// onPick is a row click (its line on the drawing; "Panel" sheet: the device card); a row with a group has an eye, a row with
// a hint shows it when the pointer stays on the row (HoldTip)
function TableView({ t, id, rowHover, hoverKeys, shown, onGroup, selected, onRow, onPick }: {
  t: SideTable; id: string; rowHover: string | null; hoverKeys: Set<string>;
  shown: Set<string> | null;
  onGroup: (group: string) => void;
  selected: Set<string> | null;
  onRow: (rid: string | null, keys: Set<string> | null) => void;
  onPick?: (keys: string[]) => void;
}) {
  const hold = useHoldTip();
  const al = (i: number) => (t.align[i] === "left" ? undefined : css.c);
  return (
    <>
      <h3>{t.title}</h3>
      {/* A table without columns is a list of notes (the installer notes on "Mounting") */}
      {t.columns.length > 0 && <table className={css.table}>
        <thead><tr>{t.columns.map((c, i) => <th key={i} className={al(i)}>{c}</th>)}</tr></thead>
        <tbody>
          {t.rows.map((r, ri) => {
            const rid = `${id}/${ri}`;
            const picked = rowPicked(selected, r.keys);
            const lit = picked || rid === rowHover || (!!r.keys && r.keys.some((k) => hoverKeys.has(k)));
            const on = !r.group || !shown || shown.has(r.group);
            return (
              <tr key={ri} className={cx(r.section && css.section, r.keys && css.linked, lit && css.lit, !on && css.off)}
                  aria-description={r.hint}
                  onPointerEnter={(e) => { if (r.keys) onRow(rid, new Set(r.keys)); if (r.hint) hold.start(r.hint, e); }}
                  onPointerMove={r.hint ? hold.move : undefined}
                  onPointerLeave={() => { if (r.keys) onRow(null, null); hold.stop(); }}
                  onClick={onPick && r.keys?.length ? () => onPick(r.keys!) : undefined}>
                {r.cells.map((c, i) => (
                  <td key={i} className={i === 0 && (r.color || r.marker) ? css.mark : al(i)}>
                    {i === 0 && r.group && <EyeToggle on={on} what={r.group} onToggle={() => onGroup(r.group!)} className={css.rowEye} />}
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
      </table>}
      {t.notes &&<ul className={css.notes}>{t.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
      {hold.tip}
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
  const { hidden, extra, electricalView } = useView((s) => s);
  useView((s) => s.themeTick);
  if (!page || !drawing) return <div className="muted">{t("side.noSheet")}</div>;
  refreshPalette();
  const colors = drawingLayers(drawing);
  const ownOfView = ownLayers(drawing, page, electricalView) ?? new Set(colors.keys());
  // A row and its colour: cable layers give several rows (layerRows); from another sheet — only
  // the purpose, protection and route are chosen on the wiring sheet
  const rows = new Map<string, string>();
  const own = new Set<string>();
  for (const [l, color] of colors) {
    if (!ownOfView.has(l)) continue;
    for (const r of layerRows(l)) { own.add(r); if (!rows.has(r)) rows.set(r, color); }
  }
  for (const [l, color] of colors) if (!ownOfView.has(l) && !rows.has(layerRows(l)[0])) rows.set(layerRows(l)[0], color);
  // Own layer: switch it off on all sheets; from another sheet: add it to the drawing
  const toggle = (l: string, on: boolean) => {
    const set = new Set(own.has(l) ? hidden : extra);
    if (own.has(l) === on) set.delete(l); else set.add(l);
    view.set(own.has(l) ? { hidden: set } : { extra: set });
  };
  // Layer row: eye (as in Photoshop) | colour | name | code; a click on the row works too
  const row = (l: string) => {
    const shown = own.has(l) ? !hidden.has(l) : extra.has(l);
    return (
      <div key={l} className={cx(css.layer, !shown && css.hiddenLayer)} onClick={() => toggle(l, !shown)}>
        <EyeToggle on={shown} what={label("layer", l)} onToggle={() => toggle(l, !shown)} />
        <span className={css.swatch} aria-hidden="true" style={{ background: screenColor(rows.get(l)!) }} />
        {label("layer", l)}
        <span className={cx(css.code, "mono")}>{l}</span>
      </div>
    );
  };
  // Cable rows in their own order, where W-CABLE stands in the alphabet
  const key = (l: string) => (CABLE_ROWS.includes(l) ? `W-CABLE ${CABLE_ROWS.indexOf(l)}` : l);
  const sorted = (ls: string[]) => ls.sort((a, b) => key(a).localeCompare(key(b)));
  const mine = sorted([...rows.keys()].filter((l) => own.has(l)));
  const rest = sorted([...rows.keys()].filter((l) => !own.has(l)));
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
