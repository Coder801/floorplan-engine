// "Estimate" tab: full-width estimates one under another, electrical (key estimate of the
// wiring page) and plumbing (the "Plumbing" page): sections, items, totals; without a price
// list, a bill of quantities. Excel is the same calculation as a file (build writes
// out/estimate.xlsx and out/plumbing-estimate.xlsx). In print, an estimate is on its stage's sheet.
// A work row with a scope (TableRow.scope) unfolds: what its price includes, what it does not
// (and where that is paid) and the handover result, so the client sees there are no hidden services.

import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { rowKind } from "@/shared/estimate";
import type { SideTable, WorkScope } from "@/shared/types";
import { HelpTip } from "@/ui/HelpTip";
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
  const scoped = table.rows.some((r) => r.scope);
  const toggle = (i: number) => setOpen((prev) => {
    const next = new Set(prev);
    if (!next.delete(i)) next.add(i);
    return next;
  });
  return (
      <article className={css.sheet}>
        <header className={css.head}>
          <h1>{table.title}</h1>
          {xlsx && <a className={css.excel} href={xlsx} download>{t("estimate.excel")}</a>}
        </header>
        {scoped && <p className={css.lead}>{t("estimate.scopeNote")}</p>}
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
      </article>
  );
}

// What the price of a work covers: two lists side by side and the result under them
function Scope({ scope }: { scope: WorkScope }) {
  const { t } = useTranslation();
  return (
    <div className={css.scopeBody}>
      <section>
        <h3>{t("estimate.includes")}</h3>
        <ul>{scope.includes.map((x) => <li key={x}>{x}</li>)}</ul>
      </section>
      {scope.excludes.length > 0 && (
        <section className={css.out}>
          <h3>{t("estimate.excludes")}</h3>
          <ul>{scope.excludes.map((x) => <li key={x}>{x}</li>)}</ul>
        </section>
      )}
      <p className={css.result}><b>{t("estimate.result")}:</b> {scope.result}</p>
    </div>
  );
}
