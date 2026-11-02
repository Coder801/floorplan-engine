// Вкладка «Общие сведения» — первая вкладка проекта (ключи overview и variants манифеста .epd):
// объект и помещения, что заложено (точки по видам, щит), сантехника (приборы, вода, канализация, смета), вариант проводки с
// выбором и сравнением всех вариантов, исходные данные и вопросы, итог проекта: электрика выбранного варианта + сантехника.
// Всё посчитано кодом при сборке (epd/overview.py, pipeline.variant_block); здесь только показ.

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import type { Overview, OverviewPlumbing, Project, VariantMode, VariantRoute, Variants, VariantSummary } from "@/shared/types";
import { VariantPicker } from "@/widgets/VariantPicker";
import { MODES, ROUTES, findVariant, parseKey } from "@/widgets/VariantPicker/variants";
import { CEILING_MAX, CEILING_MIN, parseCeiling } from "./ceiling";
import { projectTotal } from "./total";
import css from "./OverviewStage.module.scss";

interface Props {
  overview: Overview | null;
  variants: Variants | null;
  project: Project;
  openQuestions: number;
  canChoose: boolean;
  busy: boolean;
  refreshing?: boolean;  // идёт пересборка: значения скрыты заглушками, блоки на местах
  onChoose: (v: { mode: VariantMode; route: VariantRoute; distribution: "boxes" }, ceiling?: number) => void;
  onEstimate?: () => void;
  onDrawer: (tab: "questions" | "sources") => void;
}

const kw = (w: number) => (w / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 });

export function OverviewStage({ overview, variants, project, openQuestions, canChoose, busy, refreshing = false, onChoose, onEstimate, onDrawer }: Props) {
  const { t, i18n } = useTranslation();
  const num = (n: number, digits = 2) => n.toLocaleString(i18n.language, { maximumFractionDigits: digits });
  const cash = (n: number, currency: string) => `${Math.round(n).toLocaleString(i18n.language)} ${currency}`;
  const money = (s: VariantSummary) => cash(s.total, s.currency);
  // Правки копятся до «Пересчитать»: отмеченный вариант и высота потолка; после пересборки сбрасываются
  const [pending, setPending] = useState<{ mode: VariantMode; route: VariantRoute } | null>(null);
  const [ceilText, setCeilText] = useState<string | null>(null);
  useEffect(() => { setPending(null); setCeilText(null); }, [overview?.ceiling.height, variants?.active]);
  if (!overview) return <div className={css.stage}><p className="muted">{t("overview.noData")}</p></div>;
  const o = overview.object;
  const facts: [string, string][] = [
    [t("overview.object"), o.object],
    [t("overview.building"), o.building],
    [t("overview.code"), o.code],
    [t("overview.stage"), o.stage],
    [t("overview.organization"), o.organization],
  ];
  const active = variants ? parseKey(variants.active) : null;
  const current = variants && active ? findVariant(variants, active.mode, active.route) : undefined;
  const grand = projectTotal(current, overview.plumbing?.estimate);
  // Обе сметы — расшифровка итога: электрика выбранного варианта и сантехника
  const parts = grand && grand.electrical !== undefined && grand.plumbing !== undefined
    ? t("overview.totalParts", { electrical: cash(grand.electrical, grand.currency), plumbing: cash(grand.plumbing, grand.currency) })
    : null;
  const editable = canChoose && !!variants && !busy;
  const ceilNum = ceilText === null ? null : parseCeiling(ceilText);
  const ceilBad = ceilText !== null && ceilNum === null;  // введено, но не от 2000 до 4000
  const ceilNew = ceilNum !== null && ceilNum !== overview.ceiling.height ? ceilNum : undefined;
  const dirty = pending !== null || ceilNew !== undefined;
  const recalc = () => {
    if (!active || ceilBad || !dirty) return;
    onChoose({ ...(pending ?? active), distribution: "boxes" }, ceilNew);
  };
  const recalcButton = (
    <button className={css.primary} disabled={busy || ceilBad} onClick={recalc}>{t("overview.recalc")}</button>
  );
  return (
    <div className={cx(css.stage, refreshing && css.skeleton)} aria-busy={refreshing}>
      <div className={css.body}>
      <article className={css.page}>
        <header className={css.head}>
          <h1>{t("overview.title")}</h1>
          <p className="muted">{o.name}</p>
        </header>

        <section className={css.card}>
          <h2>{t("overview.object")}</h2>
          <dl className={css.pairs}>
            {facts.filter(([, v]) => v).map(([k, v]) => [<dt key={`k${k}`}>{k}</dt>, <dd key={`v${k}`}>{v}</dd>])}
            <dt>{t("overview.area")}</dt><dd>{num(overview.area)} м²</dd>
            <dt>{t("overview.ceiling")}</dt>
            <dd>
              {editable ? (
                <span className={css.edit}>
                  <input type="text" inputMode="numeric" className={cx(ceilBad && css.bad)} aria-invalid={ceilBad}
                         aria-label={t("overview.ceiling")} value={ceilText ?? String(overview.ceiling.height)}
                         onChange={(e) => setCeilText(e.target.value)} />
                  {" "}мм
                </span>
              ) : <>{num(overview.ceiling.height, 0)} мм</>}
              {overview.ceiling.assumed && ceilText === null && <span className="muted"> · {t("overview.assumed")}</span>}
              {ceilBad && <span className={css.error}> · {t("overview.ceilingRange", { min: CEILING_MIN, max: CEILING_MAX })}</span>}
            </dd>
          </dl>
          <table className={css.table}>
            <thead><tr><th>№</th><th>{t("overview.room")}</th><th className={css.num}>{t("overview.area")}, м²</th></tr></thead>
            <tbody>
              {overview.rooms.map((r, i) => (
                <tr key={r.id}>
                  <td className="muted">{i + 1}</td>
                  <td>{r.name}{r.wet && <span className={css.tag}>{t("overview.wet")}</span>}</td>
                  <td className={css.num}>{num(r.area)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {(overview.points || overview.panel) && (
          <section className={css.card}>
            <h2>{t("overview.planned")}</h2>
            {overview.points && (
              <table className={css.table}>
                <thead><tr><th>{t("overview.points")}</th><th className={css.num}>{t("overview.qty")}</th></tr></thead>
                <tbody>
                  {overview.points.map((p) => (
                    <tr key={p.key}><td>{p.text}</td><td className={css.num}>{num(p.count)} {p.unit}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
            {overview.panel && (
              <p className={css.line}>
                <b>{t("overview.panel")}:</b>{" "}
                {t("overview.panelLine", {
                  scheme: t(`overview.schemes.${overview.panel.scheme}`), input: overview.panel.input,
                  devices: overview.panel.devices, groups: overview.panel.groups,
                })}
                <br />
                <span className="muted">{t("overview.load", { installed: kw(overview.panel.installed_w), calculated: kw(overview.panel.calculated_w) })}</span>
              </p>
            )}
          </section>
        )}

        {overview.plumbing && (() => {
          const pl = overview.plumbing;
          const sewerPipes = pl.sewer.pipes.map((p) => `Ø${p.d} — ${num(p.m, 1)} м`).join(", ");
          return (
            <section className={css.card}>
              <h2>{t("overview.plumbing")}</h2>
              {pl.fixtures.length > 0 && (
                <table className={css.table}>
                  <thead><tr><th>{t("overview.fixtures")}</th><th className={css.num}>{t("overview.qty")}</th></tr></thead>
                  <tbody>
                    {pl.fixtures.map((f) => (
                      <tr key={f.type}><td>{f.text}</td><td className={css.num}>{f.count} шт</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className={css.line}>
                <b>{t("overview.water")}:</b>{" "}
                {t("overview.waterLine", {
                  distribution: t(`overview.distributions.${pl.water.distribution}`),
                  hot: t(`overview.hotFrom.${pl.water.hot ?? "none"}`),
                  cold: num(pl.water.cold_m, 1), hotM: num(pl.water.hot_m, 1), outlets: pl.water.outlets,
                })}
                <br /><span className="muted">{t("overview.waterBrand")}</span>
              </p>
              <p className={css.line}>
                <b>{t("overview.sewer")}:</b>{" "}
                {sewerPipes && <>{sewerPipes}; </>}
                {t("overview.sewerLine", { risers: pl.sewer.risers, bends: pl.sewer.bends, tees: pl.sewer.tees })}
                {pl.sewer.errors > 0 && <span className={css.error}> · {t("overview.sewerErrors", { n: pl.sewer.errors })}</span>}
              </p>
              {pl.estimate && (
                <p className={css.line}>
                  <b>{t("overview.plumbingEstimate")}:</b> {cash(pl.estimate.total, pl.estimate.currency)}
                  {pl.estimate.unpriced > 0 && <span className="muted"> · {t("overview.unpriced", { n: pl.estimate.unpriced })}</span>}
                </p>
              )}
              {pl.weak > 0 && <p className="small muted">{t("overview.weak", { n: pl.weak })}</p>}
            </section>
          );
        })()}

        {variants && (
          <section className={css.card}>
            <h2>{t("overview.variant")}</h2>
            <VariantPicker variants={variants} canChoose={canChoose} busy={busy} pending={pending} onPick={setPending} />
            {pending && <div className={css.actions}>{recalcButton}</div>}
            <h3>{t("overview.compare")}</h3>
            <div className={css.scroll}>
              <table className={cx(css.table, canChoose && css.pickable)}>
                <thead>
                  <tr>
                    <th>{t("overview.col.mode")}</th><th>{t("overview.col.route")}</th>
                    <th className={css.num}>{t("overview.col.total")}</th><th className={css.num}>{t("overview.col.cable")}</th>
                    <th className={css.num}>{t("overview.col.conduit")}</th><th className={css.num}>{t("overview.col.devices")}</th>
                    <th className={css.num}>{t("overview.col.chases")}</th>
                  </tr>
                </thead>
                <tbody>
                  {MODES.flatMap((mode) => ROUTES.map((route) => {
                    const s = findVariant(variants, mode, route);
                    if (!s) return null;
                    const on = s.key === variants.active;
                    const picked = pending?.mode === mode && pending.route === route;
                    const choose = canChoose && !busy && !on ? () => setPending(picked ? null : { mode, route }) : undefined;
                    return (
                      <tr key={s.key} className={cx(on && css.on, picked && css.picked)} onClick={choose}
                          tabIndex={choose ? 0 : undefined} onKeyDown={(e) => { if (choose && e.key === "Enter") choose(); }}
                          aria-selected={on || picked}>
                        <td>{t(`variant.modes.${mode}`)}{s.key === variants.default && <span className={css.tag}>{t("variant.asProject")}</span>}</td>
                        <td>{t(`variant.routes.${route}`)}</td>
                        <td className={css.num}>{money(s)}</td>
                        <td className={css.num}>{num(s.cable_m, 0)}</td>
                        <td className={css.num}>{num(s.conduit_m, 0)}</td>
                        <td className={css.num}>{s.devices}</td>
                        <td className={css.num}>{num(s.chases_m, 0)}</td>
                      </tr>
                    );
                  }))}
                </tbody>
              </table>
            </div>
            {canChoose && <p className="small muted">{t("overview.choose")}</p>}
          </section>
        )}

        <section className={css.card}>
          <h2>{t("overview.sources")}</h2>
          <p className={css.line}>
            {t("overview.sourcesLine", { n: project.sources.length, parsed: project.parsed?.length ?? 0 })}{" "}
            {t("overview.questions", { n: openQuestions })}
          </p>
          <div className={css.actions}>
            <button onClick={() => onDrawer("questions")}>{t("overview.openQuestions")}</button>
            <button onClick={() => onDrawer("sources")}>{t("overview.openSources")}</button>
          </div>
        </section>

      </article>
      </div>
      {grand && (
        // Итог закреплён внизу области: не уезжает с прокруткой, кнопка одного размера в обоих состояниях
        <footer className={css.dock}>
          <section className={css.total}>
            <h2>{t("overview.total")}{parts && <> · {parts}</>}</h2>
            <p className={css.sum}>{cash(grand.total, grand.currency)}</p>
            <p className={cx("small muted", !dirty && css.hidden)}>{t("overview.stale")}</p>
            <button className={css.primary} disabled={busy || ceilBad || (!dirty && !onEstimate)}
                    onClick={dirty ? recalc : onEstimate}>
              {dirty ? t("overview.recalc") : t("overview.openEstimate")}
            </button>
          </section>
        </footer>
      )}
    </div>
  );
}

// Боковая панель вкладки: вариант, итог проекта (электрика + сантехника), вопросы
interface SummaryProps {
  variants: Variants | null;
  plumbing?: OverviewPlumbing["estimate"];
  openQuestions: number;
  refreshing?: boolean;
}

export function OverviewSummary({ variants, plumbing, openQuestions, refreshing = false }: SummaryProps) {
  const { t, i18n } = useTranslation();
  const active = variants ? parseKey(variants.active) : null;
  const s = variants && active ? findVariant(variants, active.mode, active.route) : undefined;
  const grand = projectTotal(s, plumbing);
  return (
    <dl className={cx(css.side, refreshing && css.skeleton)}>
      {active && <><dt>{t("overview.variant")}</dt><dd>{t(`variant.modes.${active.mode}`)} · {t(`variant.routes.${active.route}`)}</dd></>}
      {grand && <><dt>{t("overview.total")}</dt><dd>{Math.round(grand.total).toLocaleString(i18n.language)} {grand.currency}</dd></>}
      <dt>{t("overview.openQuestions")}</dt><dd>{openQuestions}</dd>
    </dl>
  );
}
