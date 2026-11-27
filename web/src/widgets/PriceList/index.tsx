// Studio price list, a section of the studio settings (#@studio/prices): electrical works with
// the studio price and the market spread (min — median — max of public price lists,
// market.yaml), then the materials with the studio price alone (decision 2026-11-25: every item
// the price list holds), and a footnote on the period and sources. The studio edits its prices
// here (POST /api/prices) → its price list in the database, the only place it lives (decision
// 2026-11-27); the folder viewer shows it read only. Estimates take the prices at the next build,
// a project's own list changes only the keys it names. Above the tables — how wires
// are joined in the flush boxes of switches (splice: Wago clamps or crimping), saved with the
// prices by the same button.

import { Fragment, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { getPrices, savePrices } from "@/shared/api";
import { cx } from "@/shared/cx";
import { deviation, monthText, periodText, place } from "@/shared/market";
import type { MarketSpread, PricePage, PriceRow, SpliceMethod } from "@/shared/types";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Heading } from "@/ui/Heading";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Stack } from "@/ui/Stack";
import { Text } from "@/ui/Text";
import css from "./PriceList.module.scss";

const money = (v: number, lng: string) => v.toLocaleString(lng, { maximumFractionDigits: 1 });
const SPLICE: SpliceMethod[] = ["wago", "crimp"];

// onDirty — whether there are unsaved prices (the settings page asks before leaving)
export function PriceList({ onDirty }: { onDirty?: (dirty: boolean) => void }) {
  const { t, i18n } = useTranslation();
  const lng = i18n.language;
  const [data, setData] = useState<PricePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});  // edited inputs by key
  const [open, setOpen] = useState<string | null>(null);           // row with its quotes shown
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [splice, setSplice] = useState<SpliceMethod | null>(null);  // chosen, not saved yet

  useEffect(() => { getPrices().then(setData).catch((e: Error) => setError(e.message)); }, []);
  const dirty = Object.keys(draft).length > 0 || splice !== null;
  useEffect(() => { onDirty?.(dirty); }, [dirty, onDirty]);

  const names = useMemo(() => new Map(data?.market?.sources.map((s) => [s.id, s]) ?? []), [data]);
  const changes = useMemo(() => {
    const out: Record<string, number | null> = {};
    for (const [key, text] of Object.entries(draft)) {
      const v = text.trim() === "" ? null : Number(text.replace(",", "."));
      if (v !== null && (!Number.isFinite(v) || v < 0)) continue;
      out[key] = v;
    }
    return out;
  }, [draft]);
  const invalid = Object.keys(draft).length !== Object.keys(changes).length;

  const save = () => {
    setBusy(true); setError(null);
    savePrices(changes, splice ?? undefined)
      .then((d) => { setData(d); setDraft({}); setSplice(null); setSaved(true); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };
  const edit = (key: string, text: string) => { setSaved(false); setDraft((d) => ({ ...d, [key]: text })); };
  // An older server sends no splice: the build joins with Wago then
  const savedSplice: SpliceMethod = data?.splice ?? "wago";
  const pickSplice = (m: SpliceMethod) => { setSaved(false); setSplice(m === savedSplice ? null : m); };

  const name = (r: PriceRow) => (lng === "uk" ? r.name.uk : r.name.ru);
  const market = data?.market ?? null;
  // An older server sends works only, without kind
  const works = data?.rows.filter((r) => (r.kind ?? "work") === "work") ?? [];
  const materials = data?.rows.filter((r) => r.kind === "material") ?? [];

  // The studio price cell: an input for the studio, the number for others; no own price — "—"
  // (the estimate leaves the item out of the total)
  const priceCell = (r: PriceRow) => {
    const value = draft[r.key] ?? (r.price === null ? "" : String(r.price));
    return (
      <td className={css.num}>
        {data?.editable ? (
          <input className={css.input} inputMode="decimal" value={value} aria-label={t("prices.priceOf", { name: name(r) })}
                 placeholder="—"
                 onChange={(e) => edit(r.key, e.target.value)} />
        ) : r.price !== null ? money(r.price, lng) : "—"}
      </td>
    );
  };
  const period = market ? periodText(market.period, lng) : "";

  return (
    <section className={css.list} aria-labelledby="prices-title">
        <header className={css.head}>
          <Heading level={2} size="title" id="prices-title">{t("prices.title")}</Heading>
          <Text tone="muted">{t("prices.lead", { region: market?.region ?? "" })}</Text>
        </header>

        {error && <ErrorState>{error}</ErrorState>}
        {!data && !error && <EmptyState>{t("common.loading")}</EmptyState>}
        {data && (
          <>
            {data.issues.map((m) => <div key={m} className={css.issue}>{m}</div>)}
            {!!data.stale?.length && <div className={css.issue}>{t("prices.stale", { n: data.stale.length })}</div>}
            <Stack as="section" gap={2} align="start" className={css.splice} aria-labelledby="splice-title">
              <Heading level={3} size="caps" id="splice-title">{t("prices.splice.title")}</Heading>
              {data.editable ? (
                <SegmentedControl label={t("prices.splice.title")} value={splice ?? savedSplice} onChange={pickSplice}
                                  options={SPLICE.map((m) => ({ value: m, label: t(`prices.splice.${m}`) }))} />
              ) : <Text weight="medium">{t(`prices.splice.${savedSplice}`)}</Text>}
              <Text size="small" tone="muted">{t("prices.splice.hint")}</Text>
            </Stack>
            <table className={css.table}>
              <thead>
                <tr>
                  <th>{t("prices.work")}</th>
                  <th>{t("prices.unit")}</th>
                  <th className={css.num}>{t("prices.studio", { currency: data.currency })}</th>
                  <th className={css.num}>{t("prices.median")}</th>
                  <th className={css.spreadHead}>{market ? t("prices.market", { region: market.region }) : t("prices.noMarket")}</th>
                  <th className={css.num}>{t("prices.vsMedian")}</th>
                </tr>
              </thead>
              <tbody>
                {works.map((r) => {
                  const current = r.key in changes ? changes[r.key] : r.price;
                  const dev = deviation(current, r.market?.median);
                  const shown = open === r.key && r.market;
                  return (
                    <Fragment key={r.key}>
                      <tr className={cx(r.key in draft && css.changed)}>
                        <td>
                          {name(r)}
                          {r.market?.basis && <div className={cx(css.basis, "muted")}>{r.market.basis}</div>}
                        </td>
                        <td className="muted">{r.unit}</td>
                        {priceCell(r)}
                        <td className={css.num}>
                          {r.market && (
                            <span className={css.medianCell}>
                              {data.editable && current !== r.market.median && (
                                <button type="button" className={css.take} title={t("prices.takeMedianNote")} aria-label={t("prices.takeMedianNote")}
                                        onClick={() => edit(r.key, String(r.market!.median))}>{t("prices.takeMedian")}</button>
                              )}
                              <b>{money(r.market.median, lng)}</b>
                            </span>
                          )}
                        </td>
                        <td>
                          {r.market ? (
                            <div className={css.spreadCell}>
                              <Spread s={r.market} price={current} lng={lng} />
                              <button type="button" className={css.quotes} aria-expanded={open === r.key}
                                      onClick={() => setOpen(open === r.key ? null : r.key)}>
                                {t("prices.lists", { n: r.market.n })}
                              </button>
                            </div>
                          ) : <span className="muted small">{t("prices.noData")}</span>}
                        </td>
                        <td className={cx(css.num, dev !== null && Math.abs(dev) >= 50 && css.far)}>
                          {dev === null ? "" : `${dev > 0 ? "+" : ""}${dev}%`}
                        </td>
                      </tr>
                      {shown && (
                        <tr className={css.quotesRow}>
                          <td colSpan={6}>
                            <ul>
                              {r.market!.quotes.map((q) => {
                                const s = names.get(q.source);
                                return (
                                  <li key={q.source}>
                                    <b className={css.money}>{money(q.price, lng)}</b>
                                    <span>{q.text}</span>
                                    {s && <a href={s.url} target="_blank" rel="noreferrer">{s.name}</a>}
                                  </li>
                                );
                              })}
                            </ul>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>

            {materials.length > 0 && (
              <>
                <Heading level={3} size="caps" className={css.subhead}>{t("prices.materials")}</Heading>
                <table className={cx(css.table, css.materials)}>
                  <thead>
                    <tr>
                      <th>{t("prices.material")}</th>
                      <th>{t("prices.unit")}</th>
                      <th className={css.num}>{t("prices.studio", { currency: data.currency })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {materials.map((r) => (
                      <tr key={r.key} className={cx(r.key in draft && css.changed)}>
                        <td>{name(r)}</td>
                        <td className="muted">{r.unit}</td>
                        {priceCell(r)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}

            {data.editable && (
              <div className={css.actions}>
                {invalid && <Text as="span" tone="critical">{t("prices.invalid")}</Text>}
                {saved && !dirty && <Text as="span" size="small" tone="muted">{t("prices.saved")}</Text>}
                <Button disabled={busy || !dirty} onClick={() => { setDraft({}); setSplice(null); setSaved(false); }}>
                  {t("prices.reset")}
                </Button>
                <Button variant="primary" disabled={busy || invalid || (!Object.keys(changes).length && splice === null)} onClick={save}>
                  {busy ? t("prices.saving") : t("prices.save")}
                </Button>
              </div>
            )}

            {market && (
              <footer className={css.footnote}>
                <p>
                  {t("prices.footnote", {
                    region: market.region, n: market.sources.length,
                    period: period || t("prices.undatedOnly"),
                    collected: monthText(market.collected.slice(0, 7), lng).replace(/\.$/, ""),  // "р." + the sentence's own dot
                  })}
                  {market.period.undated > 0 && ` ${t("prices.undated", { n: market.period.undated })}`}
                  {` ${t("prices.method")}`}
                </p>
                <ol className={css.sources}>
                  {market.sources.map((s) => (
                    <li key={s.id}>
                      <a href={s.url} target="_blank" rel="noreferrer">{s.name}</a>
                      <span className="muted"> · {t(`prices.kinds.${s.kind}`)} · {s.date ? monthText(s.date.slice(0, 7), lng) : t("prices.noDate")}</span>
                      {s.note && <span className="muted"> · {s.note}</span>}
                    </li>
                  ))}
                </ol>
              </footer>
            )}
          </>
        )}
    </section>
  );
}

// Spread bar: whiskers min–max, the box is the middle half (Q1–Q3), the tick is the median, the
// dot is the studio price (outside the spread — at the edge, as an arrow)
function Spread({ s, price, lng }: { s: MarketSpread; price: number | null; lng: string }) {
  const { t } = useTranslation();
  const lo = s.min, hi = s.max > s.min ? s.max : s.min + 1;
  const x = (v: number) => `${Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100))}%`;
  const where = price === null ? null : place(price, s);
  return (
    <div className={css.spread}>
      <span className={cx("small muted", css.edge)}>{money(s.min, lng)}</span>
      <div className={css.bar} role="img"
           aria-label={t("prices.spreadLabel", { min: money(s.min, lng), median: money(s.median, lng), max: money(s.max, lng) })}>
        <span className={css.whisker} />
        <span className={css.box} style={{ left: x(s.q1), width: `calc(${x(s.q3)} - ${x(s.q1)})` }} />
        <span className={css.median} style={{ left: x(s.median) }} title={t("prices.median")} />
        {price !== null && where && (
          <span className={cx(css.own, css[where])} style={{ left: x(price) }} title={t(`prices.places.${where}`)} />
        )}
      </div>
      <span className={cx("small muted", css.edge)}>{money(s.max, lng)}</span>
    </div>
  );
}
