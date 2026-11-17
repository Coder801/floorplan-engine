// Side panel of a ceiling (floor) view on the elevations (decision 2026-11-17), for the installer:
// the lines of the room by panel group. Header: the count and the cable per mark in the room.
// A group row: badge in its colour, cable, lines and length in the room, an eye that hides the
// group on the view (filter3d.groups, as the group eyes of the sheet tables; the header eye hides
// or shows them all; the filter is dropped when the view changes); open, the group is its chain (tree.ts):
// the feed, then box by box the lines that leave it. A line only passing through the room is
// "transit"; a group of such lines goes last. Hover lights lanes (a group, a box's lines, a line),
// a click pins the line; rows have one height and nothing appears on hover, so the list does
// not jump. The list scrolls only to a line pinned (on the view or here), opening its group; the
// card at the bottom shows the route of the pinned line along its group.

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { toggledGroups, useView, view } from "@/shared/store";
import type { CeilingData, CeilingLine } from "@/shared/types";
import { EyeToggle } from "@/ui/EyeToggle";
import { Tag } from "@/ui/Tag";
import { Text } from "@/ui/Text";
import { cableTotals, lineGroups, routeTo, type ChainRow } from "./tree";
import css from "./CeilingLines.module.scss";

const metres = (mm: number) => (mm / 1000).toFixed(1).replace(".", ",");

export function CeilingLines({ ceiling }: { ceiling: CeilingData }) {
  const { t } = useTranslation();
  const { hover, lit, pinned, filter3d } = useView((s) => s);
  const groups = useMemo(() => lineGroups(ceiling.lines), [ceiling.lines]);
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const list = useRef<HTMLUListElement>(null);
  const revealed = useRef<string | null>(null);
  const on = (k: string) => k === hover || k === pinned || !!lit?.has(k);
  const names = useMemo(() => groups.map((g) => g.group), [groups]);
  const shown = (g: string) => !filter3d.groups || filter3d.groups.has(g);
  const allShown = names.every(shown);

  // Another view (room, plane) or leaving it: every group is shown again
  useEffect(() => () => {
    const f = view.get().filter3d;
    if (f.groups) view.set({ filter3d: { ...f, groups: null } });
  }, [ceiling.key]);

  // A line pinned on the view or here: open its group and scroll to its row, once per pin
  useEffect(() => {
    if (!pinned || pinned === revealed.current) return;
    const g = groups.find((x) => x.keys.includes(pinned));
    if (!g) return;
    if (g.rows.length > 1 && !open.has(g.group)) { setOpen(new Set(open).add(g.group)); return; }
    revealed.current = pinned;
    const row = [...(list.current?.querySelectorAll<HTMLElement>("[data-key]") ?? [])].find((el) => el.dataset.key === pinned);
    row?.scrollIntoView?.({ block: "nearest" });
  }, [pinned, open, groups]);

  const toggle = (g: string) => {
    const next = new Set(open);
    if (!next.delete(g)) next.add(g);
    setOpen(next);
  };
  const setShown = (groups: Set<string> | null) => view.set({ filter3d: { ...filter3d, groups } });
  const toggleShown = (g: string) => setShown(toggledGroups(filter3d.groups, names, g));
  const light = (keys: string[] | null) => view.set({ lit: keys ? new Set(keys) : null });
  const pin = (key: string) => view.set({ pinned: pinned === key ? null : key });

  const title = t(`ceiling.${ceiling.plane}`);
  const pinnedLine = ceiling.lines.find((ln) => ln.key === pinned) ?? null;
  return (
    <section className={css.lines}>
      <h3 className={css.title}>
        {title}<span className={css.count}>{ceiling.lines.length}</span>
        {ceiling.lines.length > 0 && (
          <EyeToggle on={allShown} what={title} className={css.allEye}
                     label={allShown ? t("ceiling.hideAll") : t("ceiling.showAll")}
                     onToggle={() => setShown(allShown ? new Set() : null)} />
        )}
      </h3>
      {ceiling.lines.length === 0 ? <Text tone="muted">{t("ceiling.none")}</Text> : (
        <>
          <Text size="small" tone="muted" className={css.cables}>
            {cableTotals(ceiling.lines).map(([mark, mm]) => t("ceiling.cable", { mark, v: metres(mm) })).join(" · ")}
          </Text>
          <ul className={css.list} ref={list}>
            {groups.map((g) => {
              const single = g.rows.length === 1 ? g.lines[0] : null;
              const opened = !single && open.has(g.group);
              const inside = !opened && g.keys.some(on);
              return [
                <li key={g.group} className={cx(css.group, inside && css.lit, g.transit && css.transit, !shown(g.group) && css.off)}
                    data-key={single?.key}
                    onPointerEnter={() => light(g.keys)} onPointerLeave={() => light(null)}
                    onClick={() => (single ? pin(single.key) : toggle(g.group))}>
                  {single ? <span className={css.chev} /> : (
                    <button type="button" className={css.chev} aria-expanded={opened}
                            aria-label={t(opened ? "ceiling.collapse" : "ceiling.expand", { g: g.group })}
                            onClick={(e) => { e.stopPropagation(); toggle(g.group); }}>{opened ? "▾" : "▸"}</button>
                  )}
                  <span className={css.mark} style={g.color ? { background: g.color } : undefined}>{g.group}</span>
                  <span className={css.name} title={single ? `${single.from} → ${single.to}` : undefined}>
                    {single ? `${single.from} → ${single.to}` : g.marks.join(", ")}
                  </span>
                  {g.transit ? <TransitTag /> : <span />}
                  <span className={cx(css.meta, "mono")}>
                    {single
                      ? t("ceiling.lineMeta", { mark: single.mark, v: metres(single.length) })
                      : t("ceiling.groupMeta", { n: g.lines.length, v: metres(g.length) })}
                  </span>
                  <EyeToggle on={shown(g.group)} what={g.group} className={css.eye}
                             onToggle={() => toggleShown(g.group)} />
                </li>,
                ...(opened ? g.rows.map((r) => (
                  <Row key={r.kind === "node" ? `${g.group}/${r.id}` : r.line.key} row={r} on={on}
                       off={!shown(g.group)} onLight={light} onPin={pin} />
                )) : []),
              ];
            })}
          </ul>
          <RouteCard line={pinnedLine} lines={ceiling.lines} />
        </>
      )}
      <Text size="small" tone="muted">{t("ceiling.note")}</Text>
    </section>
  );
}

function TransitTag() {
  const { t } = useTranslation();
  return <Tag variant="outline" title={t("ceiling.transitTitle")} className={css.tag}>{t("ceiling.transit")}</Tag>;
}

// A row of an open group: a node (its lines light up on hover) or a line ("├ 8 · Выключатель",
// "└ → К2" for the line going on to the next box)
function Row({ row, on, off, onLight, onPin }: {
  row: ChainRow;
  on: (key: string) => boolean;
  off: boolean;  // the group is hidden on the view
  onLight: (keys: string[] | null) => void;
  onPin: (key: string) => void;
}) {
  const { t } = useTranslation();
  if (row.kind === "node") {
    return (
      <li className={cx(css.node, row.keys.some(on) && css.near, off && css.off)}
          onPointerEnter={() => onLight(row.keys)} onPointerLeave={() => onLight(null)}>
        <span /><span className={css.nodeName} title={row.name}>{row.name}</span>
      </li>
    );
  }
  const ln = row.line;
  const name = row.next ? `→ ${ln.to}` : ln.to;
  return (
    <li className={cx(css.line, on(ln.key) && css.lit, off && css.off)} data-key={ln.key}
        onPointerEnter={() => onLight([ln.key])} onPointerLeave={() => onLight(null)}
        onClick={() => onPin(ln.key)}>
      <span className={css.branch} aria-hidden="true">{row.branch ? (row.tail ? "└" : "├") : ""}</span>
      <span className={css.name} title={row.branch ? ln.to : `${ln.from} → ${ln.to}`}>
        {row.branch ? name : `${ln.from} → ${ln.to}`}
      </span>
      {ln.transit ? <TransitTag /> : <span />}
      <span className={cx(css.meta, "mono")}>{t("ceiling.m", { v: metres(ln.length) })}</span>
    </li>
  );
}

// The pinned line: its route along the group chain, cable, length in the room; one height with
// or without a line, so the list above does not move
function RouteCard({ line, lines }: { line: CeilingLine | null; lines: CeilingLine[] }) {
  const { t } = useTranslation();
  if (!line) return <div className={css.card}><Text size="small" tone="muted">{t("ceiling.pick")}</Text></div>;
  const route = routeTo(lines.filter((ln) => ln.group === line.group), line).join(" → ");
  return (
    <div className={css.card} aria-live="polite">
      <Text size="caps" tone="muted">{t("ceiling.route")}</Text>
      <div className={css.route} title={route}>
        <span className={css.mark} style={line.color ? { background: line.color } : undefined}>{line.group}</span>
        <span className={css.path}>{route}</span>
      </div>
      <Text size="small" tone="muted">
        {t("ceiling.lineMeta", { mark: line.mark, v: metres(line.length) })}
        {line.transit && <> · {t("ceiling.transit")}</>}
      </Text>
    </div>
  );
}
