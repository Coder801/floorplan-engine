// Scheme of a junction box in a pinned hint: the box square with its label, the feed coming down
// from the source on the left and the cables out of it fanning to the right, one row each — point
// number (or a box mark), where it goes, cable and length; a cable of another group shows its
// group. Lines take the group colours of the sheet. A row under the cursor lights its cable and
// target on the sheet (store.lit), a click opens the target (the next box, the point). The simple
// interface mode shows only where the cables go: no group, cable or length. Not to scale: the
// route is on the sheet

import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { useView, view } from "@/shared/store";
import type { BoxBranch, BoxCable, BoxData } from "@/shared/types";
import { BOX, BOX_L, FAN_MID, fanLayout, IN_X, ROW, ROW_BRIEF, W } from "./fan";
import css from "./BoxScheme.module.scss";

interface Props {
  box: BoxData;
  colors?: Record<string, string>;   // group → colour (shared/page.ts, groupColors)
  brief?: boolean;                   // the simple interface mode
  onOpen?: (key: string) => void;    // open the target object (pin its hint)
  canOpen?: (key: string) => boolean;
}

export function BoxScheme({ box, colors = {}, brief = false, onOpen, canOpen }: Props) {
  const { t, i18n } = useTranslation();
  const hover = useView((s) => s.hover);
  const lit = useView((s) => s.lit);
  const [near, setNear] = useState<string | null>(null);  // cable key of the row under the cursor
  const ours = useRef(false);  // lit was set here: cleared when the scheme goes away
  useEffect(() => () => { if (ours.current) view.set({ lit: null }); }, []);

  const row = brief ? ROW_BRIEF : ROW;
  const { h, cy, ys } = fanLayout(box.out.length, row);
  const base = box.in?.group ?? box.out[0]?.group ?? null;
  const metres = (v: number) => t("tip.box.m", { v: new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }).format(v) });
  const meta = (c: BoxCable) => [c.group !== base ? c.group : null, c.mark, metres(c.length_m)].filter(Boolean).join(" · ");
  const color = (g: string) => colors[g] ?? null;
  const on = (c: BoxCable, target: string | null) =>
    near === c.key || hover === c.key || (!!target && hover === target) || !!lit?.has(c.key);

  const light = (c: BoxCable | null, target: string | null) => {
    setNear(c?.key ?? null);
    ours.current = !!c;
    view.set({ lit: c ? new Set([c.key, ...(target ? [target] : [])]) : null });
  };
  const open = (key: string | null) => (key && onOpen && (canOpen?.(key) ?? true) ? () => {
    light(null, null);
    onOpen(key);
  } : null);

  const feed = box.in;
  const source = feed && (
    <Line cable={feed} target={feed.from_key} lit={on(feed, feed.from_key)} light={light}
          open={open(feed.from_key)} label={t("tip.box.open", { name: feed.from })} className={css.source}>
      <span className={css.name} title={feed.from}>{feed.from}</span>
      {!brief && <span className={css.meta}>{[feed.group, feed.mark, metres(feed.length_m)].join(" · ")}</span>}
    </Line>
  );

  return (
    <div className={cx(css.scheme, brief && css.brief)} role="group"
         aria-label={t("tip.box.aria", { label: box.label, n: box.out.length })}>
      {source || <span className={cx(css.source, css.none)}>{t("tip.box.noFeed")}</span>}
      <div className={css.fan} style={{ height: h }}>
        <svg className={css.wires} width={W} height={h} viewBox={`0 0 ${W} ${h}`} aria-hidden="true">
          {feed && (
            <path className={cx(css.wire, on(feed, feed.from_key) && css.on)} style={{ stroke: color(feed.group) ?? undefined }}
                  d={`M${IN_X} 0V${cy}H${BOX_L}`} />
          )}
          {box.out.map((c, i) => (
            <path key={c.key} className={cx(css.wire, on(c, c.to_key) && css.on)} style={{ stroke: color(c.group) ?? undefined }}
                  d={`M${BOX_L + BOX} ${cy}C${FAN_MID} ${cy} ${FAN_MID} ${ys[i]} ${W} ${ys[i]}`} />
          ))}
          <rect className={css.box} x={BOX_L} y={cy - BOX / 2} width={BOX} height={BOX} />
          <text className={css.label} x={BOX_L + BOX / 2} y={cy}>{box.label}</text>
        </svg>
        <ul className={css.outs}>
          {box.out.map((c) => (
            <li key={c.key}>
              <Line cable={c} target={c.to_key} lit={on(c, c.to_key)} light={light}
                    open={open(c.to_key)} label={t("tip.box.open", { name: c.to })}>
                <Badge branch={c} color={color(c.group)} />
                <span className={css.name} title={c.to}>{c.to}</span>
                {!brief && <span className={css.meta}>{meta(c)}</span>}
              </Line>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// One cable row: a button when its target can be opened, plain text otherwise
function Line({ cable, target, lit, light, open, label, className, children }: {
  cable: BoxCable; target: string | null; lit: boolean; label: string; className?: string;
  light: (c: BoxCable | null, target: string | null) => void; open: (() => void) | null; children: ReactNode;
}) {
  const props = {
    className: cx(className, css.line, lit && css.on, !!open && css.link),
    onPointerEnter: () => light(cable, target), onPointerLeave: () => light(null, null),
  };
  return open
    ? <button type="button" {...props} title={label} onClick={open}
              onFocus={() => light(cable, target)} onBlur={() => light(null, null)}>{children}</button>
    : <div {...props}>{children}</div>;
}

// What the cable goes to: the point number on a plate of the group colour, an empty box square
// for the next box, a dot for a point without a number
function Badge({ branch, color }: { branch: BoxBranch; color: string | null }) {
  const style = color ? { background: color, borderColor: color } : undefined;
  if (branch.kind === "box") return <span className={cx(css.badge, css.toBox)} aria-hidden="true" />;
  if (branch.number == null) return <span className={cx(css.badge, css.dot)} style={style} aria-hidden="true" />;
  return <span className={cx(css.badge, "mono")} style={style}>{branch.number}</span>;
}
