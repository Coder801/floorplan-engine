// Legend: a collapsible badge in the top-left corner of the drawing (electrical and lighting
// sheets, page key legend): the icon is the same primitives as on the sheet (SVG from paths in
// sheet mm), and what it means. Point counts are in "Points", group colours in "Groups".
// Collapsed or expanded is remembered in the browser; on a narrow screen it is collapsed by default.

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { symbolBox, viewBoxOf } from "@/engine/sheet/legend";
import { cx } from "@/shared/cx";
import { refreshPalette, remember, remembered, screenColor } from "@/shared/palette";
import { useView } from "@/shared/store";
import type { Item, LegendEntry } from "@/shared/types";
import css from "./Legend.module.scss";

const KEY = "legend";  // localStorage: open | closed
const NARROW_PX = 900;
const STROKE_PX = 1.3;

export function Legend({ entries }: { entries: LegendEntry[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(() => (remembered(KEY) ?? (window.innerWidth > NARROW_PX ? "open" : "closed")) === "open");
  useView((s) => s.themeTick);  // the theme changed: recolour the icons
  if (!entries.length) return null;
  refreshPalette();
  const toggle = () => { setOpen(!open); remember(KEY, open ? "closed" : "open"); };
  return (
    <div className={cx(css.legend, open && css.open)} role="group" aria-label={t("legend.title")}>
      <button className={css.head} aria-expanded={open} onClick={toggle}>
        <span className={css.chevron} aria-hidden="true">{open ? "▾" : "▸"}</span>
        {t("legend.title")}
      </button>
      {open && (
        <ul className={css.rows}>
          {entries.map((e) => (
            <li key={e.key}>
              <Symbol items={e.items} />
              <span>{e.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Icon from the sheet: lines get one width on screen, fills (text on the panel) stay as they are
function Symbol({ items }: { items: Item[] }) {
  return (
    <svg className={css.icon} viewBox={viewBoxOf(symbolBox(items))} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      {items.map((it, i) => it.k === "f"
        ? <path key={i} d={it.d} fill={screenColor(it.c)} />
        : <path key={i} d={it.d} fill="none" stroke={screenColor(it.c)} strokeWidth={STROKE_PX}
                vectorEffect="non-scaling-stroke" strokeLinecap="round" strokeLinejoin="round" />)}
    </svg>
  );
}
