// "Overview" tab, the first project tab (manifest keys overview and variants of the .epd):
// object and rooms, what is planned (points by kind, panel), plumbing (fixtures, water, sewer,
// estimate), the wiring variant and a comparison with its neighbours (one wizard step answered
// otherwise), source data and questions, and
// the project total: electrical of the chosen variant + plumbing. Read only: every choice,
// the ceiling height too, is made in the setup wizard.
// Everything is computed by code at build time (epd/overview.py, pipeline.variant_block); this only displays it.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import type { Overview, Project, Question, Variants, VariantSummary } from "@/shared/types";
import { VariantInfo } from "@/widgets/VariantInfo";
import { anyKey } from "@/shared/i18n";
import { optionKey, type SetupProgress, type StepId } from "@/widgets/Wizard/steps";
import { activeSummary, breakersOfScheme, neighbours } from "@/widgets/VariantInfo/variants";
import { SEVERITIES, questionCounts } from "./questions";
import { projectTotal } from "./total";
import css from "./OverviewStage.module.scss";

// A name inside a sentence: "По полу" → "по полу"; "N–PE link" keeps its capitals
const lowerFirst = (s: string) => (/^.\p{Ll}/u.test(s) ? s[0].toLocaleLowerCase() + s.slice(1) : s);

interface Props {
  overview: Overview | null;
  variants: Variants | null;
  project: Project;
  openQuestions: number;
  canChoose: boolean;
  refreshing?: boolean;  // a rebuild is in progress: values hidden by placeholders, blocks in place
  onEstimate?: () => void;
  onDrawer: (tab: "questions" | "sources") => void;
  onWizard?: () => void;  // the setup wizard; none if there is nothing to ask in the project
  setup?: SetupProgress;  // decisions left in the wizard
}

const SETUP_NAMES = 3;  // decisions named in the note; the rest are a number

// What is left to decide: the estimate rests on assumptions until the wizard is done
function SetupNote({ total, open }: { total: number; open: StepId[] }) {
  const { t } = useTranslation();
  const say = anyKey(t);  // a key built from a step, as in Wizard
  const names = open.slice(0, SETUP_NAMES).map((id) => lowerFirst(say(`wizard.steps.${id}.short`))).join(", ");
  const rest = open.length - SETUP_NAMES;
  return (
    <p className={css.setupNote}>
      <b>{t("wizard.notice.title")}</b>{" "}
      {t("wizard.notice.body", { n: open.length, total, list: names })}
      {rest > 0 && ` ${t("wizard.notice.more", { n: rest })}`}.
    </p>
  );
}

const kw = (w: number) => (w / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 });

export function OverviewStage({ overview, variants, project, openQuestions, canChoose, refreshing = false, onEstimate, onDrawer, onWizard, setup }: Props) {
  const { t, i18n } = useTranslation();
  const num = (n: number, digits = 2) => n.toLocaleString(i18n.language, { maximumFractionDigits: digits });
  const cash = (n: number, currency: string) => `${Math.round(n).toLocaleString(i18n.language)} ${currency}`;
  const money = (s: VariantSummary) => cash(s.total, s.currency);
  if (!overview) return <div className={css.stage}><p className="muted">{t("overview.noData")}</p></div>;
  const o = overview.object;
  const facts: [string, string][] = [
    [t("overview.object"), o.object],
    [t("overview.building"), o.building],
    [t("overview.code"), o.code],
    [t("overview.stage"), o.stage],
    [t("overview.organization"), o.organization],
  ];
  const current = variants ? activeSummary(variants) : undefined;
  const grand = projectTotal(current, overview.plumbing?.estimate);
  // Both estimates explain the total: electrical of the chosen variant and plumbing
  const parts = grand && grand.electrical !== undefined && grand.plumbing !== undefined
    ? t("overview.totalParts", { electrical: cash(grand.electrical, grand.currency), plumbing: cash(grand.plumbing, grand.currency) })
    : null;
  // The comparison: the chosen set, then the same set with one wizard step answered otherwise,
  // and how much that changes the estimate
  const delta = (s: VariantSummary, base: VariantSummary) => {
    const d = Math.round(s.total - base.total);
    return d === 0 ? "0" : `${d > 0 ? "+" : "−"}${cash(Math.abs(d), s.currency)}`;
  };
  const say = anyKey(t);  // a key built from a step, as in Wizard
  const compareRow = (s: VariantSummary, name: ReactNode, base: VariantSummary | null, key: string) => (
    <tr key={key} className={cx(!base && css.on)}>
      <td>{name}{s.key === variants?.default && !base && <span className={css.tag}>{t("variant.asProject")}</span>}</td>
      <td className={css.num}>{money(s)}</td>
      <td className={cx(css.num, base && s.total < base.total && css.cheaper)}>{base ? delta(s, base) : ""}</td>
      <td className={css.num}>{num(s.cable_m, 0)}</td>
      <td className={css.num}>{num(s.conduit_m, 0)}</td>
      <td className={css.num}>{s.devices}</td>
      <td className={css.num}>{num(s.chases_m, 0)}</td>
    </tr>
  );
  return (
    <div className={cx(css.stage, refreshing && css.skeleton)} aria-busy={refreshing}>
      <div className={css.body}>
      <article className={css.page}>
        <header className={css.head}>
          <div>
            <h1>{t("overview.title")}</h1>
            <p className="muted">{o.name}</p>
          </div>
          {onWizard && (
            // On a wide screen the side panel lists what is left and opens the wizard (OverviewSummary)
            <div className={cx(css.setup, css.narrowOnly)}>
              {setup && setup.open.length > 0 && <SetupNote {...setup} />}
              <button className={css.primary} onClick={onWizard}>{t("wizard.open")}</button>
            </div>
          )}
        </header>

        <section className={css.card}>
          <h2>{t("overview.object")}</h2>
          <dl className={css.pairs}>
            {facts.filter(([, v]) => v).map(([k, v]) => [<dt key={`k${k}`}>{k}</dt>, <dd key={`v${k}`}>{v}</dd>])}
            <dt>{t("overview.area")}</dt><dd>{num(overview.area)} м²</dd>
            <dt>{t("overview.ceiling")}</dt>
            <dd>
              {num(overview.ceiling.height, 0)} мм
              {overview.ceiling.assumed && <span className="muted"> · {t("overview.assumed")}</span>}
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
                  scheme: lowerFirst(t(`wizard.steps.breakers.options.${breakersOfScheme(overview.panel.scheme)}.name`)), input: overview.panel.input,
                  supply: t(overview.panel.phases === 3 ? "overview.supply3" : "overview.supply1"),
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
            <VariantInfo variants={variants} canChoose={canChoose} onEdit={onWizard} />
            {current && neighbours(variants).length > 0 && (
              <>
                <h3>{t("overview.compare")}</h3>
                <p className="small muted">{t("overview.compareNote")}</p>
                <div className={css.scroll}>
                  <table className={css.table}>
                    <thead>
                      <tr>
                        <th>{t("overview.col.change")}</th>
                        <th className={css.num}>{t("overview.col.total")}</th><th className={css.num}>{t("overview.col.delta")}</th>
                        <th className={css.num}>{t("overview.col.cable")}</th><th className={css.num}>{t("overview.col.conduit")}</th>
                        <th className={css.num}>{t("overview.col.devices")}</th><th className={css.num}>{t("overview.col.chases")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {compareRow(current, t("overview.yourSet"), null, "current")}
                      {neighbours(variants).map((n) => compareRow(
                        n.summary,
                        <><span className="muted">{say(`wizard.steps.${n.step}.short`)}:</span> {lowerFirst(say(optionKey(n.step, n.value)))}</>,
                        current, `${n.step}-${n.value}`,
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>
        )}

        {/* On a wide screen the side panel holds the questions and sources (OverviewSummary) */}
        <section className={cx(css.card, css.narrowOnly)}>
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
        // The total is pinned to the bottom of the area: it does not scroll away
        <footer className={css.dock}>
          <section className={css.total}>
            <h2>{t("overview.total")}{parts && <> · {parts}</>}</h2>
            <p className={css.sum}>{cash(grand.total, grand.currency)}</p>
            <button className={css.primary} disabled={!onEstimate} onClick={onEstimate}>{t("overview.openEstimate")}</button>
          </section>
        </footer>
      )}
    </div>
  );
}

// Tab side panel (decision 2026-11-11): what is left to do, always in sight while the page
// scrolls: the setup progress (wizard steps, an open one opens the wizard on it) and the
// unresolved questions by weight. Below the narrow breakpoint the panel folds under the drawing,
// so the page keeps its own note and "Source data" card there
interface SummaryProps {
  setup: SetupProgress | null;
  questions: Question[];
  onWizard?: (step?: StepId) => void;  // none: no right to choose, the list is read only
  onDrawer: (tab: "questions" | "sources") => void;
  refreshing?: boolean;
}

// A decided step: a plain check, not a ring (a ring reads as a radio button)
function CheckIcon() {
  return (
    <svg className={css.check} viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function OverviewSummary({ setup, questions, onWizard, onDrawer, refreshing = false }: SummaryProps) {
  const { t } = useTranslation();
  const say = anyKey(t);  // a key built from a step, as in Wizard
  const counts = questionCounts(questions);
  const open = SEVERITIES.reduce((n, s) => n + counts[s], 0);
  const done = setup ? setup.total - setup.open.length : 0;
  return (
    <div className={cx(css.sideBody, refreshing && css.skeleton)}>
      {setup && setup.total > 0 && (
        <section className={css.block}>
          <h3>{t("overview.progress.title")}</h3>
          <ul className={css.steps}>
            {setup.steps.map((id) => {
              const todo = setup.open.includes(id);
              const name = say(`wizard.steps.${id}.short`);
              return (
                <li key={id} className={cx(todo && css.todo)}>
                  <span className={css.mark} role="img" aria-label={t(todo ? "overview.progress.open" : "overview.progress.decided")}>
                    {todo ? <span className={css.dash} /> : <CheckIcon />}
                  </span>
                  {todo && onWizard
                    ? <button className={css.stepLink} onClick={() => onWizard(id)}>{name}</button>
                    : <span>{name}</span>}
                </li>
              );
            })}
          </ul>
          <p className={cx("small muted", css.note)}>
            {setup.open.length ? t("overview.progress.done", { done, total: setup.total }) : t("overview.progress.all")}
          </p>
          {onWizard && (
            <button className={css.wizardOpen} onClick={() => onWizard()}>{t("wizard.open")}</button>
          )}
        </section>
      )}
      <section className={css.block}>
        <h3>{t("overview.openQuestions")}</h3>
        {open === 0 ? <p className="small muted">{t("overview.progress.noQuestions")}</p> : (
          <dl className={css.side}>
            {SEVERITIES.filter((s) => counts[s] > 0).map((s) => [
              <dt key={`k${s}`}><span className={`sev-${s}`} aria-hidden="true">●</span> {t(`severity.${s}`)}</dt>,
              <dd key={`v${s}`}>{counts[s]}</dd>,
            ])}
          </dl>
        )}
        <div className={css.actions}>
          <button onClick={() => onDrawer("questions")}>{t("overview.openQuestions")}</button>
          <button onClick={() => onDrawer("sources")}>{t("overview.openSources")}</button>
        </div>
      </section>
    </div>
  );
}
