// Small shared parts: status word with a dot, an error line, column widths of a table, a dialog,
// a section header, loading of one request. Buttons (icon, copy, in-place confirmation) — buttons.tsx.
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { STATE, word } from "@/shared/text";
import { Icon } from "./icons";
import css from "./ui.module.scss";

export const cx = (...names: (string | false | null | undefined)[]) => names.filter(Boolean).join(" ");

export function Status({ state, label }: { state: string; label?: string }) {
  const text = label ?? word(STATE, state);
  return <span className={css.status} title={text}><i className={cx(css.dot, css[state])} />{text}</span>;
}

export function ErrorLine({ error }: { error: string | null }) {
  return error ? <div className={css.error} role="alert">{error}</div> : null;
}

/** Column widths of a table (table-layout: fixed): a number is pixels, null shares the rest. The
 *  widths do not follow the content, so a table keeps its columns when rows change. */
export function Cols({ w }: { w: (number | null)[] }) {
  return <colgroup>{w.map((x, i) => <col key={i} style={x === null ? undefined : { width: x }} />)}</colgroup>;
}

/** Widths of the usual columns, px (mono 12 px, padding 8 + 8 included). */
export const W = {
  day: 112,    // "до 03.11.2026"
  time: 156,   // "до 03.11.2026 14:05"
  ago: 96,     // "5 мин", or a date
  num: 72,     // a count
  role: 136,   // "хозяин квартиры"
  status: 116, // "действует"
  slug: 160,   // a project folder
  act: 48,     // one icon button (28) with the cell's padding
};

export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);
  return (
    <div className={css.backdrop} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={css.dialog} role="dialog" aria-label={title}>
        <div className={css.dialogHead}>{title}<button type="button" className={css.iconBtn} onClick={onClose} aria-label="Закрыть"><Icon name="x" /></button></div>
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
