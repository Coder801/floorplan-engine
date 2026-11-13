// Setup wizard: a popup with the steps on the left and one question in the middle, cards with
// pictures or a field. What it asks depends on the project (steps.ts). Nothing is written until
// "Apply": the choices go together, with one rebuild (api.saveWizard). Until then they are a draft
// that survives a reload (draft.ts). An unanswered step stays an open question; the assumption of
// the model is only marked on its card.

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import type { WizardBody } from "@/shared/api";
import { REDUCED_MOTION } from "@/shared/consts";
import { cx } from "@/shared/cx";
import { anyKey } from "@/shared/i18n";
import { FADE_MS } from "@/shared/popover";
import { plainNumber } from "@/shared/questions";
import type { OverviewMaster, OverviewReserve, Project, Scene, Variants, VariantSummary } from "@/shared/types";
import { Button } from "@/ui/Button";
import { Card } from "@/ui/Card";
import { Heading } from "@/ui/Heading";
import { IconButton } from "@/ui/IconButton";
import { Tag } from "@/ui/Tag";
import { Text } from "@/ui/Text";
import { FlatCut } from "@/widgets/FlatCut";
import { CEILING_MAX, CEILING_MIN, parseCeiling } from "./ceiling";
import { ReserveList } from "@/widgets/ReserveList";
import { reserveOn } from "@/widgets/ReserveList/reserve";
import { MasterList } from "@/widgets/MasterList";
import { masterOn } from "@/widgets/MasterList/master";
import { findChoice } from "@/widgets/VariantInfo/variants";
import { WizardArt } from "@/widgets/WizardArt";
import { clearDraft, loadDraft, samePicks, saveDraft } from "./draft";
import { UNKNOWN, VARIANT_STEPS, applyPick, chasesKept, initialPicks, invalid, isPicked, optionKey, otherQuestions, setupOf, variantOf, wizardBody, wizardSteps, type Picks, type Step, type StepId } from "./steps";
import css from "./Wizard.module.scss";

const DONE = "done";
const FOCUSABLE = "button:not(:disabled), input, a[href]";
// Steps whose question text carries numbers of this project (a current, a battery breaker)
const WITH_FACTS = new Set<StepId>(["input", "power", "battery"]);
// Unit of a number step
const unitOf = (id: StepId) => (id === "ceiling" ? "units.mm" : id === "power" ? "units.kw" : "units.a");

interface Props {
  project: Project;
  variants: Variants | null;
  ceiling: { height: number; assumed: boolean } | null;
  scene?: Scene | null;  // the flat in 3D: the ceiling step shows it cut away (FlatCut)
  reserve: OverviewReserve | null;
  master?: OverviewMaster | null;
  onApply: (body: WizardBody) => Promise<boolean>;  // false: the person stayed, nothing was saved
  onClose: () => void;
  onQuestions: () => void;
  start?: StepId;  // open on this step (from the overview's "Progress" list); a saved draft yields to it
}

export function Wizard({ project, variants, ceiling, scene = null, reserve, master = null, onApply, onClose, onQuestions, start }: Props) {
  const { t, i18n } = useTranslation();
  const say = anyKey(t);  // keys built from a step and its values
  const setup = useMemo(() => setupOf(project, variants, ceiling?.height ?? null, reserve, master), [project, variants, ceiling, reserve, master]);
  const before = useMemo(() => initialPicks(setup), [setup]);
  const [draft] = useState(() => loadDraft(project.id, project.built));
  const [picks, setPicks] = useState<Picks>(() => ({ ...before, ...draft?.picks }));
  const [restored, setRestored] = useState(!!draft && !samePicks(before, { ...before, ...draft.picks }));
  const [at, setAt] = useState<StepId | typeof DONE>(() => {
    const shown = wizardSteps(setup, { ...before, ...draft?.picks });
    if (start && shown.some((s) => s.id === start)) return start;
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
  // A list of groups always shows a set (the project's one until changed): "next" agrees with it,
  // so the step is decided, not skipped
  const shownGroups = (s: Step) =>
    (s.id === "masterOff" && master ? masterOn(master).join() : s.id === "reserve" && reserve ? reserveOn(reserve).join() : undefined);
  const next = (s: Step) => {
    const shown = isPicked(picks[s.id]) ? undefined : shownGroups(s);
    if (shown !== undefined) pick(s.id, shown);
    go(1);
  };

  const money = (s: VariantSummary | undefined) =>
    (s ? `${Math.round(s.total).toLocaleString(i18n.language)} ${s.currency}` : "");
  // Only the saved set and its neighbours (one step answered otherwise) are computed: a step gets
  // prices if all its cards have one, that is while the other steps are as saved
  const summary = (id: StepId, value: string) =>
    (variants ? findChoice(variants, variantOf(setup, applyPick(picks, id, value))) : undefined);
  const priced = !!step && VARIANT_STEPS.has(step.id) && step.options.every((value) => summary(step.id, value));
  const optionName = (s: Step, value: string): string => {
    if (value === UNKNOWN) return t("wizard.unknown");
    if (s.kind === "groups") return value.split(",").join(", ");
    if (s.kind === "number") return `${plainNumber(value)} ${t(unitOf(s.id))}`;
    return say(optionKey(s.id, value));
  };
  // What "don't know" leaves in the project, as a person reads it
  const unknownNote = (s: Step) => {
    const assumed = s.question?.assumption ?? s.assumed;
    if (s.kind === "groups") return t("wizard.unknownGroups");
    return assumed === undefined || assumed === null ? t("wizard.unknownNote")
      : t("wizard.unknownValue", { value: optionName(s, plainNumber(assumed)) });
  };
  const optionNote = (s: Step, value: string) =>
    (value === UNKNOWN ? unknownNote(s) : say(`wizard.steps.${s.id}.options.${value}.note`));
  // The value the model holds now: marked on the card, not chosen for the person
  const inModel = (s: Step, value: string) => {
    const assumed = s.question?.assumption ?? s.assumed;
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
    if (ev.key === "Escape") { ev.stopPropagation(); close(); }
    if (ev.key !== "Tab" || !box.current) return;
    const all = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    const first = all[0], last = all[all.length - 1];
    const now = document.activeElement;
    if (ev.shiftKey && (now === first || now === box.current)) { ev.preventDefault(); last?.focus(); }
    else if (!ev.shiftKey && now === last) { ev.preventDefault(); first?.focus(); }
  };

  const reset = () => { setPicks(before); setRestored(false); setError(null); };
  // Closing fades out first (global.scss data-closing), then the parent unmounts the wizard
  const [closing, setClosing] = useState(false);
  const close = () => {
    if (closing) return;
    setClosing(true);
    setTimeout(onClose, REDUCED_MOTION ? 0 : FADE_MS);
  };

  const others = otherQuestions(setup, steps);
  const kept = chasesKept(picks);
  const estimate = variants && picks.route ? findChoice(variants, variantOf(setup, picks)) : undefined;
  const groups = (["wiring", "panel", "reserve", "extra"] as const).filter((g) => steps.some((s) => s.group === g));
  const shownTitle = step ? say(`wizard.steps.${step.id}.title`) : t("wizard.done.title");
  const position = step ? index + 1 : steps.length + 1;

  return (
    <div className={css.veil} data-veil="" data-closing={closing || undefined}>
      <div ref={box} className={css.dialog} data-pop="modal" data-closing={closing || undefined} role="dialog" aria-modal="true" aria-labelledby="wizard-title"
           tabIndex={-1} onKeyDown={onKey}>
        <nav className={css.steps} aria-label={t("wizard.stepsLabel")}>
          <Heading level={2} size="subheading" id="wizard-title" className={css.title}>{t("wizard.title")}</Heading>
          {groups.map((g) => (
            <div key={g}>
              <Heading level={3} size="caps" className={css.group}>{t(`wizard.groups.${g}`)}</Heading>
              <ol>
                {steps.filter((s) => s.group === g).map((s) => {
                  const on = s.id === at;
                  return (
                    <li key={s.id}>
                      <button type="button" className={cx(css.step, on && css.on)} aria-current={on ? "step" : undefined} onClick={() => setAt(s.id)}>
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
          <button type="button" className={cx(css.step, at === DONE && css.on)} aria-current={at === DONE ? "step" : undefined} onClick={() => setAt(DONE)}>
            {t("wizard.groups.done")}
          </button>
        </nav>

        <div className={css.head}>
          <Text as="span" size="small" tone="muted">
            {t("wizard.stepOf", { n: position, total: steps.length + 1 })}
            {restored && <> · {t("wizard.restored")} <Button variant="link" onClick={reset}>{t("wizard.reset")}</Button></>}
          </Text>
          <IconButton variant="close" label={t("common.close")} onClick={close} />
        </div>

        <section className={css.body}>
          <Heading level={1}>{shownTitle}</Heading>
          {step ? (
            <>
              <Text tone="muted">{say(`wizard.steps.${step.id}.why`)}</Text>
              {step.kind === "cards" ? (
                <div className={css.cards} role="radiogroup" aria-label={shownTitle}>
                  {step.options.map((value) => {
                    const s = priced ? summary(step.id, value) : undefined;
                    return (
                      <Card as="button" type="button" key={value} role="radio" aria-checked={picks[step.id] === value}
                            padding="sm" interactive selected={picks[step.id] === value} className={css.card}
                            onClick={() => pick(step.id, value)}>
                        <WizardArt name={value === UNKNOWN ? UNKNOWN : `${step.id}-${value}`} />
                        <b>{optionName(step, value)}</b>
                        {s && <span className={css.price}>{money(s)}</span>}
                        <Text as="span" size="small" tone="muted">{optionNote(step, value)}</Text>
                        {s && <Text as="span" size="small" tone="muted">{t("wizard.routeFacts", { cable: Math.round(s.cable_m), chases: Math.round(s.chases_m) })}</Text>}
                        {inModel(step, value) && <Tag variant="outline" tone="inherit" className={css.current}>{t("wizard.current")}</Tag>}
                      </Card>
                    );
                  })}
                </div>
              ) : step.id === "masterOff" ? (
                <>
                  <MasterList master={master!} value={picks.masterOff && picks.masterOff !== UNKNOWN ? picks.masterOff.split(",") : masterOn(master!)}
                              onChange={(groups) => pick("masterOff", groups.join())}
                              unknown={{ on: picks.masterOff === UNKNOWN, note: unknownNote(step), onPick: () => pick("masterOff", UNKNOWN) }} />
                </>
              ) : step.kind === "groups" ? (
                <>
                  <ReserveList reserve={reserve!} value={picks.reserve && picks.reserve !== UNKNOWN ? picks.reserve.split(",") : reserveOn(reserve!)}
                               onChange={(groups) => pick("reserve", groups.join())} />
                  <div className={css.presets}>
                    <Button size="sm" pressed={picks.reserve === UNKNOWN} onClick={() => pick("reserve", UNKNOWN)}>{t("wizard.unknown")}</Button>
                  </div>
                  {picks.reserve === UNKNOWN && <Text size="small" tone="muted">{unknownNote(step)}</Text>}
                </>
              ) : (
                <div className={css.number}>
                  <div className={css.picture}>
                    {step.id === "ceiling" && scene
                      ? <FlatCut scene={scene} height={parseCeiling(picks[step.id] ?? "") ?? ceiling?.height ?? scene.ceiling} />
                      : <WizardArt name={step.id} />}
                  </div>
                  <div className={css.field}>
                    <label>
                      <Text as="span" size="small" tone="muted">{say(`wizard.steps.${step.id}.field`)}</Text>
                      <span className={css.input}>
                        <input type="text" inputMode="numeric" aria-invalid={invalid(step, picks[step.id])}
                               className={cx(invalid(step, picks[step.id]) && css.bad)}
                               value={picks[step.id] === UNKNOWN ? "" : picks[step.id] ?? ""} placeholder={step.question?.assumption != null ? plainNumber(step.question.assumption) : undefined}
                               onChange={(e) => pick(step.id, e.target.value.trim())} />
                        {t(unitOf(step.id))}
                      </span>
                    </label>
                    <div className={css.presets}>
                      {step.options.map((value) => (
                        <Button key={value} size="sm" pressed={picks[step.id] === value} onClick={() => pick(step.id, value)}>{value}</Button>
                      ))}
                      {step.question && (
                        <Button size="sm" pressed={picks[step.id] === UNKNOWN} onClick={() => pick(step.id, UNKNOWN)}>{t("wizard.unknown")}</Button>
                      )}
                    </div>
                    {picks[step.id] === UNKNOWN && <Text size="small" tone="muted">{unknownNote(step)}</Text>}
                    {invalid(step, picks[step.id]) && (
                      <Text tone="major">
                        {step.id === "ceiling"
                          ? t("overview.ceilingRange", { min: CEILING_MIN, max: CEILING_MAX })
                          : t("wizard.badInput")}
                      </Text>
                    )}
                    {step.id === "ceiling" && ceiling?.assumed && <Text size="small" tone="muted">{t("overview.assumed")}</Text>}
                  </div>
                </div>
              )}
              {VARIANT_STEPS.has(step.id) && !priced && <Text size="small" tone="muted">{t("wizard.noPrices")}</Text>}
              {step.id === "plaster" && kept && <p className={css.fact}>{t(`wizard.chasesKept.${kept}`)}</p>}
              {step.question && WITH_FACTS.has(step.id) && (
                <p className={css.fact}><b>{t("wizard.inProject")}</b> {step.question.text}</p>
              )}
            </>
          ) : (
            <>
              <Text tone="muted">{changed ? t("wizard.done.note") : t("wizard.done.empty")}</Text>
              <dl className={css.result}>
                {steps.map((s) => {
                  const value = picks[s.id];
                  const moved = isPicked(value) && value !== before[s.id];
                  return [
                    <dt key={`k${s.id}`}>{t(`wizard.steps.${s.id}.short`)}</dt>,
                    <dd key={`v${s.id}`} className={cx(!isPicked(value) && "muted")}>
                      {isPicked(value) ? optionName(s, value!) : t("wizard.done.unset")}
                      {moved && <Tag variant="outline" className={css.changed}>{t("wizard.done.changed")}</Tag>}
                    </dd>,
                  ];
                })}
              </dl>
              {estimate ? (
                <Text size="small">
                  {t("wizard.done.total", { total: money(estimate) })}
                  <span className="muted"> · {t("wizard.done.totalNote")}</span>
                </Text>
              ) : variants && changed && <Text size="small" tone="muted">{t("wizard.done.totalLater")}</Text>}
              {others > 0 && (
                <Text size="small">
                  {t("wizard.done.others", { n: others })}{" "}
                  <Button variant="link" onClick={onQuestions}>{t("overview.openQuestions")}</Button>
                </Text>
              )}
              {wrong && <Text tone="major">{t("wizard.done.wrong", { step: t(`wizard.steps.${wrong.id}.short`) })}</Text>}
              {error && <Text tone="major" role="alert">{error}</Text>}
            </>
          )}
        </section>

        <footer className={css.foot}>
          <Button disabled={at === steps[0]?.id} onClick={() => go(at === DONE ? steps.length - 1 - index : -1)}>{t("wizard.back")}</Button>
          {step ? (
            <Button variant="primary" className={css.primary} disabled={invalid(step, picks[step.id])} onClick={() => next(step)}>
              {isPicked(picks[step.id]) || shownGroups(step) !== undefined ? t("wizard.next") : t("wizard.skip")}
            </Button>
          ) : changed ? (
            <Button variant="primary" className={css.primary} disabled={!!wrong} onClick={apply}>{t("wizard.done.apply")}</Button>
          ) : (
            <Button variant="primary" className={css.primary} onClick={close}>{t("common.close")}</Button>
          )}
        </footer>
      </div>
    </div>
  );
}

