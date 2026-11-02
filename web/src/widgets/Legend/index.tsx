// Условные обозначения — сворачиваемая плашка в левом верхнем углу чертежа (листы электрики
// и освещения, ключ legend страницы): значок — те же примитивы, что на листе (SVG из путей
// в мм листа), и что он значит. Количество точек — в «Точках», цвета групп — в «Группах».
// Свёрнута или развёрнута — помнится в браузере; на узком экране по умолчанию свёрнута.

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
  useView((s) => s.themeTick);  // сменилась тема — перекрасить значки
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

// Значок с листа: линии — одной толщины на экране, заливки (текст на щите) — как есть
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
