// Scheme of a flush box where wires are joined (key splice of a point card, decision 2026-11-25):
// drawn like the junction box scheme (BoxScheme, fan.ts) — the incoming cable comes down from its
// source on the left, the box is a circle with a dot per joint, the cables out fan to the right,
// one row each; a cable whose phase runs on from the device terminals is dashed. Below — a node
// per conductor: what it joins (the feed, the cables out by point number, the taps to the
// devices) and with what (a Wago model or a sleeve), the cables off the terminals, the method and
// the depth of the box. A cable row lights the cable on the sheet, a click opens the line; a
// joint row lights all its cables. The simple interface mode drops groups, cables and lengths.
// Not to scale: the route is on the sheet

import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import type { BoxCable, SpliceData, SpliceJoint } from "@/shared/types";
import { Text } from "@/ui/Text";
import { BOX, BOX_L, FAN_MID, fanLayout, IN_X, ROW, ROW_BRIEF, W } from "@/widgets/BoxScheme/fan";
import { CableBadge } from "@/widgets/CableBadge";
import { CableLine } from "@/widgets/CableLine";
import { useCableLight } from "@/widgets/CableLine/light";
import { clampModels, jointCables, offTerminals } from "./joints";
import css from "./SpliceScheme.module.scss";

interface Props {
  splice: SpliceData;
  colors?: Record<string, string>;   // group → colour (shared/page.ts, groupColors)
  brief?: boolean;                   // the simple interface mode
  onOpen?: (key: string) => void;    // open the line (pin its hint)
  canOpen?: (key: string) => boolean;
}

const DOT_GAP = 9;  // px between the joint dots inside the box circle
const COND_CLASS = { L: css.l, N: css.n, PE: css.pe } as const;

export function SpliceScheme({ splice, colors = {}, brief = false, onOpen, canOpen }: Props) {
  const { t, i18n } = useTranslation();
  const { light, on } = useCableLight();

  const row = brief ? ROW_BRIEF : ROW;
  const { h, cy, ys } = fanLayout(splice.out.length, row);
  const r = BOX / 2, cx0 = BOX_L + r;
  const terminals = offTerminals(splice);
  const base = splice.in?.group ?? splice.out[0]?.group ?? null;
  const metres = (v: number) => t("tip.box.m", { v: new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }).format(v) });
  const meta = (c: BoxCable) => (brief ? null : [
    c.group !== base ? c.group : null, c.mark, metres(c.length_m), terminals.has(c.key) ? t("tip.splice.terminalsHint") : null,
  ].filter(Boolean).join(" · "));
  const color = (g: string) => colors[g] ?? null;
  const lighter = (c: BoxCable, target: string | null) => (yes: boolean) =>
    light(yes ? [c.key, ...(target ? [target] : [])] : null);
  // A cable row opens its line, as a click on it on the sheet
  const open = (key: string) => (onOpen && (canOpen?.(key) ?? true) ? () => {
    light(null);
    onOpen(key);
  } : null);
  const byKey = new Map(splice.out.map((c) => [c.key, c]));
  const how = (j: SpliceJoint) => (splice.method === "crimp" || !j.clamps.length
    ? t("tip.splice.sleeve")
    : t("tip.splice.clamp", { model: clampModels(j) }));
  const notes = [
    t(splice.method === "crimp" ? "tip.splice.crimp" : "tip.splice.wago"),
    t("tip.splice.deep", { mm: splice.deep_mm }),
    ...(splice.devices > 1 ? [t("tip.splice.devices", { n: splice.devices })] : []),
  ];

  const feed = splice.in;
  const dots = splice.joints.map((j, i) => (
    <circle key={j.conductor} className={cx(css.dot, COND_CLASS[j.conductor])} r={3}
            cx={cx0} cy={cy + (i - (splice.joints.length - 1) / 2) * DOT_GAP} />
  ));

  return (
    <div className={cx(css.scheme, brief && css.brief)} role="group"
         aria-label={t("tip.splice.aria", { n: splice.joints.length })}>
      <div className={css.cables}>
        {feed
          ? <CableLine source brief={brief} name={feed.from} lit={on(feed.key, feed.from_key)} onLight={lighter(feed, feed.from_key)}
                       meta={brief ? null : [feed.group, feed.mark, metres(feed.length_m)].join(" · ")}
                       open={open(feed.key)} label={t("tip.splice.open", { name: feed.from })} />
          : <span className={css.none}>{t("tip.box.noFeed")}</span>}
        <div className={css.fan} style={{ height: h }}>
          <svg className={css.wires} width={W} height={h} viewBox={`0 0 ${W} ${h}`} aria-hidden="true">
            {feed && (
              <path className={cx(css.wire, on(feed.key, feed.from_key) && css.on)} style={{ stroke: color(feed.group) ?? undefined }}
                    d={`M${IN_X} 0V${cy}H${BOX_L}`} />
            )}
            {splice.out.map((c, i) => (
              <path key={c.key} className={cx(css.wire, terminals.has(c.key) && css.terminal, on(c.key, c.to_key) && css.on)}
                    style={{ stroke: color(c.group) ?? undefined }}
                    d={`M${BOX_L + BOX} ${cy}C${FAN_MID} ${cy} ${FAN_MID} ${ys[i]} ${W} ${ys[i]}`} />
            ))}
            <circle className={css.box} cx={cx0} cy={cy} r={r} />
            {dots}
          </svg>
          <ul className={css.outs}>
            {splice.out.map((c) => (
              <li key={c.key}>
                <CableLine brief={brief} name={c.to} meta={meta(c)} badge={<CableBadge branch={c} color={color(c.group)} />}
                           lit={on(c.key, c.to_key)} onLight={lighter(c, c.to_key)}
                           open={open(c.key)} label={t("tip.splice.open", { name: c.to })} />
              </li>
            ))}
          </ul>
        </div>
      </div>
      <Text size="caps" tone="muted">{t("tip.splice.joints")}</Text>
      <ul className={css.joints}>
        {splice.joints.map((j) => (
          <li key={j.conductor} className={css.joint} title={t("tip.splice.wires", { n: j.wires })}
              onPointerEnter={() => light(jointCables(splice, j))} onPointerLeave={() => light(null)}>
            <abbr className={cx(css.cond, COND_CLASS[j.conductor])} title={t(`tip.splice.cond.${j.conductor}`)}>{j.conductor}</abbr>
            <span className={css.parts}>
              {feed && <span>{t("tip.splice.in")}</span>}
              {j.out.map((k) => {
                const c = byKey.get(k);
                return c ? <CableBadge key={k} branch={c} color={color(c.group)} small /> : null;
              })}
              {j.taps > 0 && <span>{j.taps > 1 ? t("tip.splice.tapN", { n: j.taps }) : t("tip.splice.tap")}</span>}
            </span>
            <span className={css.how}>{how(j)}</span>
          </li>
        ))}
        {terminals.size > 0 && (
          <li className={css.joint} onPointerEnter={() => light([...terminals])} onPointerLeave={() => light(null)}>
            <span className={css.dash} aria-hidden="true" />
            <span className={css.parts}>
              {[...terminals].map((k) => <CableBadge key={k} branch={byKey.get(k)!} color={color(byKey.get(k)!.group)} small />)}
            </span>
            <span className={css.how}>{t("tip.splice.terminals")}</span>
          </li>
        )}
      </ul>
      <Text size="small" tone="muted">{notes.join(" · ")}</Text>
    </div>
  );
}
