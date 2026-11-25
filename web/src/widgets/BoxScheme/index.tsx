// Scheme of a junction box in a pinned hint: the box square with its label, the feed coming down
// from the source on the left and the cables out of it fanning to the right, one row each — point
// number (or a box mark), where it goes, cable and length; a cable of another group shows its
// group. Lines take the group colours of the sheet. A row under the cursor lights its cable and
// target on the sheet (store.lit), a click opens the target (the next box, the point). The simple
// interface mode shows only where the cables go: no group, cable or length. Not to scale: the
// route is on the sheet

import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import type { BoxCable, BoxData } from "@/shared/types";
import { CableBadge } from "@/widgets/CableBadge";
import { CableLine } from "@/widgets/CableLine";
import { useCableLight } from "@/widgets/CableLine/light";
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
  const { light, on } = useCableLight();

  const row = brief ? ROW_BRIEF : ROW;
  const { h, cy, ys } = fanLayout(box.out.length, row);
  const base = box.in?.group ?? box.out[0]?.group ?? null;
  const metres = (v: number) => t("tip.box.m", { v: new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }).format(v) });
  const meta = (c: BoxCable) => [c.group !== base ? c.group : null, c.mark, metres(c.length_m)].filter(Boolean).join(" · ");
  const color = (g: string) => colors[g] ?? null;
  // A row lights its cable and target; a click opens the target, if it can be opened
  const lighter = (c: BoxCable, target: string | null) => (yes: boolean) =>
    light(yes ? [c.key, ...(target ? [target] : [])] : null);
  const open = (key: string | null) => (key && onOpen && (canOpen?.(key) ?? true) ? () => {
    light(null);
    onOpen(key);
  } : null);

  const feed = box.in;
  const source = feed && (
    <CableLine source brief={brief} name={feed.from} lit={on(feed.key, feed.from_key)} onLight={lighter(feed, feed.from_key)}
               meta={brief ? null : [feed.group, feed.mark, metres(feed.length_m)].join(" · ")}
               open={open(feed.from_key)} label={t("tip.box.open", { name: feed.from })} />
  );

  return (
    <div className={cx(css.scheme, brief && css.brief)} role="group"
         aria-label={t("tip.box.aria", { label: box.label, n: box.out.length })}>
      {source || <span className={css.none}>{t("tip.box.noFeed")}</span>}
      <div className={css.fan} style={{ height: h }}>
        <svg className={css.wires} width={W} height={h} viewBox={`0 0 ${W} ${h}`} aria-hidden="true">
          {feed && (
            <path className={cx(css.wire, on(feed.key, feed.from_key) && css.on)} style={{ stroke: color(feed.group) ?? undefined }}
                  d={`M${IN_X} 0V${cy}H${BOX_L}`} />
          )}
          {box.out.map((c, i) => (
            <path key={c.key} className={cx(css.wire, on(c.key, c.to_key) && css.on)} style={{ stroke: color(c.group) ?? undefined }}
                  d={`M${BOX_L + BOX} ${cy}C${FAN_MID} ${cy} ${FAN_MID} ${ys[i]} ${W} ${ys[i]}`} />
          ))}
          <rect className={css.box} x={BOX_L} y={cy - BOX / 2} width={BOX} height={BOX} />
          <text className={css.label} x={BOX_L + BOX / 2} y={cy}>{box.label}</text>
        </svg>
        <ul className={css.outs}>
          {box.out.map((c) => (
            <li key={c.key}>
              <CableLine brief={brief} name={c.to} meta={brief ? null : meta(c)} badge={<CableBadge branch={c} color={color(c.group)} />}
                         lit={on(c.key, c.to_key)} onLight={lighter(c, c.to_key)}
                         open={open(c.to_key)} label={t("tip.box.open", { name: c.to })} />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
