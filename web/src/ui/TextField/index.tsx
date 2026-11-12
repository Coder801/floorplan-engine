// A one-line text field with its label above, a hint or an error under it. mono is for codes and
// numbers; size lg is the login and phone target. Without label the field needs aria-label.

import { useId, type InputHTMLAttributes, type ReactNode, type Ref } from "react";
import { cx } from "@/shared/cx";
import css from "./TextField.module.scss";

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  mono?: boolean;
  size?: "md" | "lg";
  inputClassName?: string;   // the input itself (className is the wrapper)
  ref?: Ref<HTMLInputElement>;
}

export function TextField({ label, hint, error, mono, size = "md", className, inputClassName, id, ref, ...rest }: Props) {
  const own = useId();
  const fid = id ?? own;
  const note = error ? `${fid}-error` : hint ? `${fid}-hint` : undefined;
  return (
    <div className={cx(css.field, className)}>
      {label && <label className={css.label} htmlFor={fid}>{label}</label>}
      <input ref={ref} id={fid} className={cx(css.input, css[size], mono && css.mono, !!error && css.invalid, inputClassName)}
             aria-invalid={error ? true : undefined} aria-describedby={note} {...rest} />
      {error ? <span id={note} className={css.error} role="alert">{error}</span>
        : hint && <span id={note} className={css.hint}>{hint}</span>}
    </div>
  );
}
