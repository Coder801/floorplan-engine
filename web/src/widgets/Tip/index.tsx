// Object hint: at the cursor (right and below; if it does not fit, on the other side) or, pinned
// by a click, in the top-right corner, not over the drawing; closed by ×, Esc (on the sheet and
// in 3D) and by switching sheets (store.resetSelection)

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import type { PageIndex } from "@/shared/page";
import { useView, view } from "@/shared/store";
import css from "./Tip.module.scss";

const unpin = () => view.set({ selected: null, neighbors: null, pinned: null });

export function Tip({ index }: { index: PageIndex }) {
  const { t } = useTranslation();
  const { tip, pinned } = useView((s) => s);
  const el = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const key = pinned || tip?.key || null;

  useEffect(() => {
    if (!pinned) return;
    const onKey = (ev: KeyboardEvent) => { if (ev.key === "Escape") unpin(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pinned]);

  useLayoutEffect(() => {
    const node = el.current;
    if (!node || pinned || !tip) { setPos(null); return; }
    const box = node.parentElement!.getBoundingClientRect();
    const tw = node.offsetWidth, th = node.offsetHeight, { x, y } = tip;
    setPos({
      left: x + 16 + tw > box.width ? Math.max(x - 16 - tw, 4) : x + 16,
      top: y + 16 + th > box.height ? Math.max(y - 16 - th, 4) : y + 16,
    });
  }, [tip, pinned]);

  if (!key) return null;
  const card = index.card(key);
  return (
    <div ref={el} className={cx(css.tip, !!pinned && css.docked)}
         style={pinned ? undefined : { left: pos?.left ?? -9999, top: pos?.top ?? -9999 }}>
      {pinned && <button className={css.close} aria-label={t("tip.close")} onClick={unpin}>×</button>}
      <b>{card.title}</b>
      {card.rows.length > 0 && (
        <dl>{card.rows.map(([k, v], i) => [<dt key={`t${i}`}>{k}</dt>, <dd key={`d${i}`}>{v}</dd>])}</dl>
      )}
    </div>
  );
}
