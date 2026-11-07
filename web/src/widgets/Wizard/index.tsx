// Setup wizard: a popup with the steps on the left and one question in the middle, cards with
// pictures or a field. What it asks depends on the project (steps.ts). Nothing is written until
// "Apply": the choices go together, with one rebuild (api.saveWizard). Until then they are a draft
// that survives a reload (draft.ts). An unanswered step stays an open question; the assumption of
// the model is only marked on its card.

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import type { WizardBody } from "@/shared/api";
import { cx } from "@/shared/cx";
import { plainNumber } from "@/shared/questions";
import type { OverviewReserve, Project, Variants, VariantSummary } from "@/shared/types";
import { CEILING_MAX, CEILING_MIN } from "./ceiling";
import { ReserveList } from "@/widgets/ReserveList";
import { reserveOn } from "@/widgets/ReserveList/reserve";
import { findChoice } from "@/widgets/VariantInfo/variants";
import { WizardArt } from "@/widgets/WizardArt";
import { clearDraft, loadDraft, samePicks, saveDraft } from "./draft";
import { UNKNOWN, VARIANT_STEPS, applyPick, chasesKept, initialPicks, invalid, isPicked, otherQuestions, setupOf, variantOf, wizardBody, wizardSteps, type Picks, type Step, type StepId } from "./steps";
import css from "./Wizard.module.scss";

const DONE = "done";
const FOCUSABLE = "button:not(:disabled), input, a[href]";
// Steps whose question text carries numbers of this project (a current, a battery breaker)
const WITH_FACTS = new Set<StepId>(["input", "battery"]);

interface Props {
  project: Project;
  variants: Variants | null;
  ceiling: { height: number; assumed: boolean } | null;
  reserve: OverviewReserve | null;
  onApply: (body: WizardBody) => Promise<boolean>;  // false: the person stayed, nothing was saved
  onClose: () => void;
  onQuestions: () => void;
}

export function Wizard({ project, variants, ceiling, reserve, onApply, onClose, onQuestions }: Props) {
  const { t, i18n } = useTranslation();
  // Keys built from a step and its values: the same cast as i18n label()
  const say = t as unknown as (key: string) => string;
  const setup = useMemo(() => setupOf(project, variants, ceiling?.height ?? null, reserve), [project, variants, ceiling, reserve]);
  const before = useMemo(() => initialPicks(setup), [setup]);
  const [draft] = useState(() => loadDraft(project.id, project.built));
  const [picks, setPicks] = useState<Picks>(() => ({ ...before, ...draft?.picks }));
  const [restored, setRestored] = useState(!!draft && !samePicks(before, { ...before, ...draft.picks }));
  const [at, setAt] = useState<StepId | typeof DONE>(() => {
    const shown = wizardSteps(setup, { ...before, ...draft?.picks });
    return draft && (draft.step === DONE || shown.some((s) => s.id === draft.step)) ? draft.step : shown[0]?.id ?? DONE;
  });
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { box.current?.focus(); }, []);
  useEffect(() => {
    if (samePicks(picks, before)) clearDraft(project.id);
    else saveDraft(project.id, project.built, { picks, step: at });
  }, [picks, at, before, project.id, project.built]);

  const steps = wizardSteps(setup, picks);
  const index = steps.findIndex((s) => s.id === at);
  const step = index >= 0 ? steps[index] : null;
  const wrong = steps.find((s) => invalid(s, picks[s.id]));
  const body = wizardBody(setup, picks);
  const changed = !!body.variant || !!body.answers;
  const pick = (id: StepId, value: string) => { setPicks((p) => applyPick(p, id, value)); setError(null); };
  const go = (delta: number) => setAt(steps[index + delta]?.id ?? DONE);

  const money = (s: VariantSummary | undefined) =>
    (s ? `${Math.round(s.total).toLocaleString(i18n.language)} ${s.currency}` : "");
  // Only the modes and the current variant are computed: a step gets prices if all its cards have one
  const summary = (id: StepId, value: string) =>
    (variants ? findChoice(variants, variantOf(setup, applyPick(picks, id, value))) : undefined);
  const priced = !!step && VARIANT_STEPS.has(step.id) && step.options.every((value) => summary(step.id, value));
  const optionName = (s: Step, value: string): string => {
    if (value === UNKNOWN) return t("wizard.unknown");
    if (s.id === "route") return say(`variant.routes.${value}`);
    if (s.kind === "groups") return value.split(",").join(", ");
    if (s.kind === "number") return `${plainNumber(value)} ${t(s.id === "ceiling" ? "units.mm" : "units.a")}`;
    return say(`wizard.steps.${s.id}.options.${value}.name`);
  };
  // What "don't know" leaves in the project, as a person reads it
  const unknownNote = (s: Step) => {
    const assumed = s.question?.assumption;
    if (s.kind === "groups") return t("wizard.unknownGroups");
    return assumed === undefined || assumed === null ? t("wizard.unknownNote")
      : t("wizard.unknownValue", { value: optionName(s, plainNumber(assumed)) });
  };
  const optionNote = (s: Step, value: string) =>
    (value === UNKNOWN ? unknownNote(s) : say(`wizard.steps.${s.id}.options.${value}.note`));
  // The value the model holds now: marked on the card, not chosen for the person
  const inModel = (s: Step, value: string) => {
    const assumed = s.question?.assumption;
    if (value === UNKNOWN) return false;
    return ((before[s.id] === UNKNOWN ? undefined : before[s.id]) ?? (assumed === undefined || assumed === null ? undefined : plainNumber(assumed))) === value;
  };

  const apply = () => {
    setError(null);
    onApply(body).then(
      (done) => { if (done) clearDraft(project.id); },
      (e: Error) => setError(t("wizard.failed", { message: e.message })),
    );
  };
  const onKey = (ev: KeyboardEvent) => {
    if (ev.key === "Escape") { ev.stopPropagation(); onClose(); }
    if (ev.key !== "Tab" || !box.current) return;
    const all = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    const first = all[0], last = all[all.length - 1];
    const now = document.activeElement;
    if (ev.shiftKey && (now === first || now === box.current)) { ev.preventDefault(); last?.focus(); }
    else if (!ev.shiftKey && now === last) { ev.preventDefault(); first?.focus(); }
  };

  const reset = () => { setPicks(before); setRestored(false); setError(null); };

  const others = otherQuestions(setup, steps);
  const kept = chasesKept(picks);
  const estimate = variants && picks.route ? findChoice(variants, variantOf(setup, picks)) : undefined;
  const groups = (["wiring", "panel", "reserve"] as const).filter((g) => steps.some((s) => s.group === g));
  const shownTitle = step ? say(`wizard.steps.${step.id}.title`) : t("wizard.done.title");
  const position = step ? index + 1 : steps.length + 1;

  return (
    <div className={css.veil}>
      <div ref={box} className={css.dialog} role="dialog" aria-modal="true" aria-labelledby="wizard-title"
           tabIndex={-1} onKeyDown={onKey}>
        <nav className={css.steps} aria-label={t("wizard.stepsLabel")}>
          <h2 id="wizard-title">{t("wizard.title")}</h2>
          {groups.map((g) => (
            <div key={g}>
              <h3>{t(`wizard.groups.${g}`)}</h3>
              <ol>
                {steps.filter((s) => s.group === g).map((s) => {
                  const on = s.id === at;
                  return (
                    <li key={s.id}>
                      <button className={cx(css.step, on && css.on)} aria-current={on ? "step" : undefined} onClick={() => setAt(s.id)}>
                        <span className={cx(css.mark, isPicked(picks[s.id]) && css.picked)} aria-hidden="true">
                          {isPicked(picks[s.id]) ? "✓" : ""}
                        </span>
                        <span>{t(`wizard.steps.${s.id}.short`)}</span>
                      </button>
                    </li>
                  );
                })}
              </ol>
            </div>
          ))}
          <button className={cx(css.step, at === DONE && css.on)} aria-current={at === DONE ? "step" : undefined} onClick={() => setAt(DONE)}>
            {t("wizard.groups.done")}
          </button>
        </nav>

        <div className={css.head}>
          <span className="small muted">
            {t("wizard.stepOf", { n: position, total: steps.length + 1 })}
            {restored && <> · {t("wizard.restored")} <button className={css.link} onClick={reset}>{t("wizard.reset")}</button></>}
          </span>
          <button className={css.close} aria-label={t("common.close")} onClick={onClose}>×</button>
        </div>

        <section className={css.body}>
          <h1>{shownTitle}</h1>
          {step ? (
            <>
              <p className="muted">{say(`wizard.steps.${step.id}.why`)}</p>
              {step.kind === "cards" ? (
                <div className={css.cards} role="radiogroup" aria-label={shownTitle}>
                  {step.options.map((value) => {
                    const s = priced ? summary(step.id, value) : undefined;
                    return (
                      <button key={value} role="radio" aria-checked={picks[step.id] === value}
                              className={cx(css.card, picks[step.id] === value && css.chosen)}
                              onClick={() => pick(step.id, value)}>
                        <WizardArt name={value === UNKNOWN ? UNKNOWN : `${step.id}-${value}`} />
                        <b>{optionName(step, value)}</b>
                        {s && <span className={css.price}>{money(s)}</span>}
                        <span className="small muted">{optionNote(step, value)}</span>
                        {s && <span className="small muted">{t("wizard.routeFacts", { cable: Math.round(s.cable_m), chases: Math.round(s.chases_m) })}</span>}
                        {inModel(step, value) && <span className={cx(css.tag, css.current)}>{t("wizard.current")}</span>}
                      </button>
                    );
                  })}
                </div>
              ) : step.kind === "groups" ? (
                <>
                  <ReserveList reserve={reserve!} value={picks.reserve && picks.reserve !== UNKNOWN ? picks.reserve.split(",") : reserveOn(reserve!)}
                               onChange={(groups) => pick("reserve", groups.join())} />
                  <div className={css.presets}>
                    <button aria-pressed={picks.reserve === UNKNOWN} className={cx(picks.reserve === UNKNOWN && css.chosen)}
                            onClick={() => pick("reserve", UNKNOWN)}>{t("wizard.unknown")}</button>
                  </div>
                  {picks.reserve === UNKNOWN && <p className="small muted">{unknownNote(step)}</p>}
                </>
              ) : (
                <div className={css.number}>
                  <div className={css.picture}><WizardArt name={step.id} /></div>
                  <div className={css.field}>
                    <label>
                      <span className="small muted">{say(`wizard.steps.${step.id}.field`)}</span>
                      <span className={css.input}>
                        <input type="text" inputMode="numeric" aria-invalid={invalid(step, picks[step.id])}
                               className={cx(invalid(step, picks[step.id]) && css.bad)}
                               value={picks[step.id] === UNKNOWN ? "" : picks[step.id] ?? ""} placeholder={step.question?.assumption != null ? plainNumber(step.question.assumption) : undefined}
                               onChange={(e) => pick(step.id, e.target.value.trim())} />
                        {t(step.id === "ceiling" ? "units.mm" : "units.a")}
                      </span>
                    </label>
                    <div className={css.presets}>
                      {step.options.map((value) => (
                        <button key={value} aria-pressed={picks[step.id] === value} className={cx(picks[step.id] === value && css.chosen)}
                                onClick={() => pick(step.id, value)}>{value}</button>
                      ))}
                      {step.question && (
                        <button aria-pressed={picks[step.id] === UNKNOWN} className={cx(picks[step.id] === UNKNOWN && css.chosen)}
                                onClick={() => pick(step.id, UNKNOWN)}>{t("wizard.unknown")}</button>
                      )}
                    </div>
                    {picks[step.id] === UNKNOWN && <p className="small muted">{unknownNote(step)}</p>}
                    {invalid(step, picks[step.id]) && (
                      <p className={css.error}>
                        {step.id === "ceiling"
                          ? t("overview.ceilingRange", { min: CEILING_MIN, max: CEILING_MAX })
                          : t("wizard.badInput")}
                      </p>
                    )}
                    {step.id === "ceiling" && ceiling?.assumed && <p className="small muted">{t("overview.assumed")}</p>}
                  </div>
                </div>
              )}
              {VARIANT_STEPS.has(step.id) && !priced && <p className="small muted">{t("wizard.noPrices")}</p>}
              {step.id === "plaster" && kept && <p className={css.fact}>{t(`wizard.chasesKept.${kept}`)}</p>}
              {step.question && WITH_FACTS.has(step.id) && (
                <p className={css.fact}><b>{t("wizard.inProject")}</b> {step.question.text}</p>
              )}
            </>
          ) : (
            <>
              <p className="muted">{changed ? t("wizard.done.note") : t("wizard.done.empty")}</p>
              <dl className={css.result}>
                {steps.map((s) => {
                  const value = picks[s.id];
                  const moved = isPicked(value) && value !== before[s.id];
                  return [
                    <dt key={`k${s.id}`}>{t(`wizard.steps.${s.id}.short`)}</dt>,
                    <dd key={`v${s.id}`} className={cx(!isPicked(value) && "muted")}>
                      {isPicked(value) ? optionName(s, value!) : t("wizard.done.unset")}
                      {moved && <span className={css.tag}>{t("wizard.done.changed")}</span>}
                    </dd>,
                  ];
                })}
              </dl>
              {estimate ? (
                <p className="small">
                  {t("wizard.done.total", { total: money(estimate) })}
                  <span className="muted"> · {t("wizard.done.totalNote")}</span>
                </p>
              ) : variants && changed && <p className="small muted">{t("wizard.done.totalLater")}</p>}
              {others > 0 && (
                <p className="small">
                  {t("wizard.done.others", { n: others })}{" "}
                  <button className={css.link} onClick={onQuestions}>{t("overview.openQuestions")}</button>
                </p>
              )}
              {wrong && <p className={css.error}>{t("wizard.done.wrong", { step: t(`wizard.steps.${wrong.id}.short`) })}</p>}
              {error && <p className={css.error} role="alert">{error}</p>}
            </>
          )}
        </section>

        <footer className={css.foot}>
          <button disabled={at === steps[0]?.id} onClick={() => go(at === DONE ? steps.length - 1 - index : -1)}>{t("wizard.back")}</button>
          {step ? (
            <button className={css.primary} disabled={invalid(step, picks[step.id])} onClick={() => go(1)}>
              {isPicked(picks[step.id]) ? t("wizard.next") : t("wizard.skip")}
            </button>
          ) : changed ? (
            <button className={css.primary} disabled={!!wrong} onClick={apply}>{t("wizard.done.apply")}</button>
          ) : (
            <button className={css.primary} onClick={onClose}>{t("common.close")}</button>
          )}
        </footer>
      </div>
    </div>
  );
}
