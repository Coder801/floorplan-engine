// "Estimate" tab: full-width estimates one under another, electrical (key estimate of the
// wiring page) and plumbing (the "Plumbing" page): sections, items, totals; without a price
// list, a bill of quantities. Excel is the same calculation as a file (build writes
// out/estimate.xlsx and out/plumbing-estimate.xlsx). In print, an estimate is on its stage's sheet.
// A work row with a scope (TableRow.scope) unfolds: what its price includes and the handover
// result, so the client sees there are no hidden services. The title, Excel and the column headings
// stay on top while the estimate scrolls.

import { Fragment, useEffect, useState, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { rowKind } from "@/shared/estimate";
import type { SideTable, WorkScope } from "@/shared/types";
import { Button } from "@/ui/Button";
import { Card } from "@/ui/Card";
import { Heading } from "@/ui/Heading";
import { HelpTip } from "@/ui/HelpTip";
import { Text } from "@/ui/Text";
import css from "./EstimateStage.module.scss";

export interface EstimateItem { table: SideTable; xlsx: string | null }

export function EstimateStage({ items }: { items: EstimateItem[] }) {
  return (
    <div className={css.stage}>
      {items.map((it) => <Estimate key={it.table.title} table={it.table} xlsx={it.xlsx} />)}
    </div>
  );
}

function Estimate({ table, xlsx }: EstimateItem) {
  const { t } = useTranslation();
  const al = (i: number) => (table.align[i] === "left" ? undefined : css.num);
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set());
  const headH = useHeight<HTMLElement>();
  const scoped = table.rows.some((r) => r.scope);
  const toggle = (i: number) => setOpen((prev) => {
    const next = new Set(prev);
    if (!next.delete(i)) next.add(i);
    return next;
  });
  return (
      <Card as="article" padding="lg" className={css.sheet} style={{ "--head-h": `${headH.height}px` } as CSSProperties}>
        <header ref={headH.ref} className={css.head}>
          <Heading level={1}>{table.title}</Heading>
          {xlsx && <Button variant="primary" href={xlsx} download>{t("estimate.excel")}</Button>}
        </header>
        {scoped && <Text size="small" tone="muted">{t("estimate.scopeNote")}</Text>}
        <table className={css.table}>
          <thead><tr>{table.columns.map((c, i) => <th key={i} className={al(i)}>{c}</th>)}</tr></thead>
          <tbody>
            {table.rows.map((r, ri) => {
              const kind = rowKind(r);
              const missing = kind === "line" && r.cells.includes("—");
              const shown = !!r.scope && open.has(ri);
              const name = (c: string) => (r.scope ? (
                <button type="button" className={css.more} aria-expanded={shown} onClick={() => toggle(ri)}>
                  <span className={css.chevron} aria-hidden="true" />
                  {c}
                </button>
              ) : c);
              return (
                <Fragment key={ri}>
                  <tr className={cx(css[kind], missing && css.missing, shown && css.opened)}>
                    {r.cells.map((c, i) => (
                      <td key={i} className={al(i)}>
                        {i === 1 && r.hint ? (
                          <span className={css.named}>
                            {name(c)}
                            <HelpTip label={t("estimate.about", { name: c })} text={r.hint} mark="i" size={18} align="left" />
                          </span>
                        ) : i === 1 ? name(c) : c}
                      </td>
                    ))}
                  </tr>
                  {shown && r.scope && (
                    <tr className={css.scope}>
                      <td />
                      <td colSpan={r.cells.length - 1}><Scope scope={r.scope} /></td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {table.total && (
              <tr className={css.total}>{table.total.map((c, i) => <td key={i} className={al(i)}>{c}</td>)}</tr>
            )}
          </tbody>
        </table>
        {!!table.notes?.length && <ul className={css.notes}>{table.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
      </Card>
  );
}

// Height of an element, kept up to date: the sticky column headings sit right under the sticky head,
// whose height changes when the title wraps (phone, a long name)
function useHeight<T extends HTMLElement>() {
  const [height, setHeight] = useState(0);
  const [node, ref] = useState<T | null>(null);
  useEffect(() => {
    if (!node || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setHeight(node.offsetHeight));
    ro.observe(node);
    return () => ro.disconnect();
  }, [node]);
  return { height, ref };
}

// What the price of a work covers: the operations and the result under them
function Scope({ scope }: { scope: WorkScope }) {
  const { t } = useTranslation();
  return (
    <div className={css.scopeBody}>
      <section>
        <Heading level={3} size="subheading">{t("estimate.includes")}</Heading>
        <ul>{scope.includes.map((x) => <li key={x}>{x}</li>)}</ul>
      </section>
      <p className={css.result}><b>{t("estimate.result")}:</b> {scope.result}</p>
    </div>
  );
}
