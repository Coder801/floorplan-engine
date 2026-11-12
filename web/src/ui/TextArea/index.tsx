// A multi-line text field: label above, a counter on the label line (counter, e.g. "12 / 2000"),
// a hint or an error under it. Grows by hand (resize vertical).

import { useId, type ReactNode, type Ref, type TextareaHTMLAttributes } from "react";
import { cx } from "@/shared/cx";
import css from "./TextArea.module.scss";

interface Props extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: ReactNode;
  counter?: ReactNode;
  over?: boolean;          // the counter is over the limit
  hint?: ReactNode;
  error?: ReactNode;
  ref?: Ref<HTMLTextAreaElement>;
}

export function TextArea({ label, counter, over, hint, error, className, id, rows = 3, ref, ...rest }: Props) {
  const own = useId();
  const fid = id ?? own;
  const note = error ? `${fid}-error` : hint ? `${fid}-hint` : undefined;
  return (
    <div className={cx(css.field, className)}>
      {(label || counter) && (
        <span className={css.head}>
          {label && <label className={css.label} htmlFor={fid}>{label}</label>}
          {counter && <span className={cx(css.counter, over && css.over)} aria-live="polite">{counter}</span>}
        </span>
      )}
      <textarea ref={ref} id={fid} rows={rows} className={cx(css.area, !!error && css.invalid)}
                aria-invalid={error ? true : undefined} aria-describedby={note} {...rest} />
      {error ? <span id={note} className={css.error} role="alert">{error}</span>
        : hint && <span id={note} className={css.hint}>{hint}</span>}
    </div>
  );
}
