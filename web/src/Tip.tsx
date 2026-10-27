// Подсказка объекта: у курсора (справа и ниже, не помещается — по другую сторону) или
// закреплённая кликом — в правом верхнем углу, не поверх чертежа

import { useLayoutEffect, useRef, useState } from "react";
import type { PageIndex } from "./page";
import { useView } from "./store";

export function Tip({ index }: { index: PageIndex }) {
  const { tip, pinned } = useView((s) => s);
  const el = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const key = pinned || tip?.key || null;

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
    <div ref={el} className={pinned ? "tip docked" : "tip"}
         style={pinned ? undefined : { left: pos?.left ?? -9999, top: pos?.top ?? -9999 }}>
      <b>{card.title}</b>
      {card.rows.length > 0 && (
        <dl>{card.rows.map(([k, v], i) => [<dt key={`t${i}`}>{k}</dt>, <dd key={`d${i}`}>{v}</dd>])}</dl>
      )}
    </div>
  );
}
