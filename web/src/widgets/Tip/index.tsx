// Object hint: at the cursor (right and below; if it does not fit, on the other side) or, pinned
// by a click, in the top-right corner, not over the drawing; closed by ×, Esc (on the sheet and
// in 3D) and by switching sheets (store.resetSelection). A pinned socket block also shows its
// scheme and a link to the elevation of the whole wall, a pinned junction box — its cables
// (BoxScheme: a row opens the next box or the point), a point whose flush box joins wires — its
// joints (SpliceScheme: a row opens the line; on the wiring sheet also at the cursor, it is what
// the mark on the symbol is about). The simple interface mode shows the short card of a line or a
// box: where it runs, without group, cable and lengths

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { briefCard, type PageIndex } from "@/shared/page";
import { useView, view } from "@/shared/store";
import { Button } from "@/ui/Button";
import { IconButton } from "@/ui/IconButton";
import { BoxScheme } from "@/widgets/BoxScheme";
import { PointBlock } from "@/widgets/PointBlock";
import { SpliceScheme } from "@/widgets/SpliceScheme";
import css from "./Tip.module.scss";

const unpin = () => view.set({ selected: null, neighbors: null, pinned: null });

interface Props {
  index: PageIndex;
  onWall?: (key: string) => void;
  colors?: Record<string, string>;  // group colours of the drawing, for the box scheme
  canOpen?: (o: string) => boolean;  // which rows of the schemes open; any object of the page by default
  hoverSplice?: boolean;  // the joints of a flush box at the cursor too, not only pinned (wiring sheet)
}

export function Tip({ index, onWall, colors, canOpen, hoverSplice = false }: Props) {
  const { t } = useTranslation();
  const { tip, pinned, cables } = useView((s) => s);
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
  const full = index.card(key);
  const card = cables ? full : briefCard(key, full);
  const { block } = card;
  const { box, splice } = full;  // the simple mode shows them too, without cables and lengths
  const openable = canOpen ?? ((o: string) => index.interactive(o));
  // A row of the box scheme: its target is pinned, as by a click on the sheet
  const open = (o: string) => {
    const chain = index.chainOf(o);
    view.set({ selected: chain, neighbors: index.neighborsOf(chain), pinned: o, tip: null });
  };
  return (
    <div ref={el} className={cx(css.tip, !!pinned && css.docked)}
         style={pinned ? undefined : { left: pos?.left ?? -9999, top: pos?.top ?? -9999 }}
         // The canvas keeps focus, so Esc on the sheet still clears the selection after a click here
         onMouseDown={(ev) => ev.preventDefault()}>
      {pinned && <IconButton variant="close" size="sm" className={css.close} label={t("tip.close")} onClick={unpin} />}
      <b>{card.title}</b>
      {card.rows.length > 0 && (
        <dl>{card.rows.map(([k, v], i) => [<dt key={`t${i}`}>{k}</dt>, <dd key={`d${i}`}>{v}</dd>])}</dl>
      )}
      {(pinned || hoverSplice) && splice && (
        <SpliceScheme key={key} splice={splice} colors={colors} brief={!cables} onOpen={open} canOpen={openable} />
      )}
      {pinned && block && <PointBlock block={block} />}
      {pinned && box && <BoxScheme box={box} colors={colors} brief={!cables} onOpen={open} canOpen={openable} />}
      {pinned && block && onWall && (
        <Button size="sm" block className={css.wall} onClick={() => onWall(block.wall)}>{t("tip.openWall")}</Button>
      )}
    </div>
  );
}
