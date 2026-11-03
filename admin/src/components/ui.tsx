// Small shared parts: status word with a dot, in-place confirmation, an error line, a dialog,
// a section header, loading of one request.
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { STATE, word } from "@/shared/text";
import css from "./ui.module.scss";

export const cx = (...names: (string | false | null | undefined)[]) => names.filter(Boolean).join(" ");

export function Status({ state, label }: { state: string; label?: string }) {
  return <span className={css.status}><i className={cx(css.dot, css[state])} />{label ?? word(STATE, state)}</span>;
}

export function ErrorLine({ error }: { error: string | null }) {
  return error ? <div className={css.error} role="alert">{error}</div> : null;
}

/** A dangerous action asks right where it is: "Убрать? [Да] [Нет]", no modal. */
export function Confirm({ label, question, onYes, disabled }: {
  label: string; question: string; onYes: () => void; disabled?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) return <button className={css.danger} disabled={disabled} onClick={() => setAsking(true)}>{label}</button>;
  return (
    <span className={css.actions}>
      <span>{question}</span>
      <button className={css.danger} onClick={() => { setAsking(false); onYes(); }}>Да</button>
      <button onClick={() => setAsking(false)}>Нет</button>
    </span>
  );
}

export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);
  return (
    <div className={css.backdrop} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={css.dialog} role="dialog" aria-label={title}>
        <div className={css.dialogHead}>{title}<button onClick={onClose} aria-label="Закрыть">×</button></div>
        {children}
      </div>
    </div>
  );
}

export function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className={css.section}>
      <div className={css.sectionHead}><span>{title}</span>{action}</div>
      {children}
    </section>
  );
}

export function Segmented({ options, value, onChange, label }: {
  options: string[]; value: string; onChange: (v: string) => void; label: (v: string) => string;
}) {
  return (
    <span className={css.segmented}>
      {options.map((o) => (
        <button key={o} className={cx(o === value && css.on)} onClick={() => onChange(o)}>{label(o)}</button>
      ))}
    </span>
  );
}

export interface Load<T> { data: T | null; error: string | null; reload: () => void; set: (t: T) => void }

/** One request: data, error, reload; set replaces the data with a fresh answer of a change. */
export function useLoad<T>(fetcher: () => Promise<T>, deps: unknown[]): Load<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  useEffect(() => {
    let live = true;
    setError(null);
    fetcher().then((d) => live && setData(d)).catch((e: Error) => live && setError(e.message));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, reload, set: setData };
}

/** Run a change: the error (a 409 reason) goes next to the action, success — to onDone. */
export function useAction() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = useCallback(async <T,>(fn: () => Promise<T>, onDone?: (t: T) => void) => {
    setBusy(true);
    setError(null);
    try {
      const t = await fn();
      onDone?.(t);
      return t;
    } catch (e) {
      setError((e as Error).message);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { error, busy, run, clear: () => setError(null) };
}

export { css };
