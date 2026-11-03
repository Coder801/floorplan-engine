// "Estimate" tab: full-width estimates one under another, electrical (key estimate of the
// wiring page) and plumbing (the "Plumbing" page): sections, items, totals; without a price
// list, a bill of quantities. Excel is the same calculation as a file (build writes
// out/estimate.xlsx and out/plumbing-estimate.xlsx). In print, an estimate is on its stage's sheet.

import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { rowKind } from "@/shared/estimate";
import type { SideTable } from "@/shared/types";
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
  return (
      <article className={css.sheet}>
        <header className={css.head}>
          <h1>{table.title}</h1>
          {xlsx && <a className={css.excel} href={xlsx} download>{t("estimate.excel")}</a>}
        </header>
        <table className={css.table}>
          <thead><tr>{table.columns.map((c, i) => <th key={i} className={al(i)}>{c}</th>)}</tr></thead>
          <tbody>
            {table.rows.map((r, ri) => {
              const kind = rowKind(r);
              const missing = kind === "line" && r.cells.includes("—");
              return (
                <tr key={ri} className={cx(css[kind], missing && css.missing)}>
                  {r.cells.map((c, i) => (
                    <td key={i} className={al(i)}>
                      {i === 1 && r.hint ? (
                        <span className={css.named}>
                          {c}
                          <HelpTip label={t("estimate.about", { name: c })} text={r.hint} mark="i" size={18} align="left" />
                        </span>
                      ) : c}
                    </td>
                  ))}
                </tr>
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
