// A checkbox with its label: the native input (keyboard, forms, screen readers), the label
// beside it is clickable. note is a second line under the label; indeterminate is "some of them".

import { useEffect, useRef, type InputHTMLAttributes, type ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./Checkbox.module.scss";

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "onChange"> {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: ReactNode;      // without it, aria-label is needed (a table cell)
  note?: ReactNode;
  indeterminate?: boolean;
}

export function Checkbox({ checked, onChange, label, note, indeterminate = false, className, disabled, ...rest }: Props) {
  const box = useRef<HTMLInputElement>(null);
  useEffect(() => { if (box.current) box.current.indeterminate = indeterminate; }, [indeterminate]);
  return (
    <label className={cx(css.check, disabled && css.disabled, !label && css.bare, className)}>
      <input ref={box} type="checkbox" className={css.box} checked={checked} disabled={disabled}
             onChange={(e) => onChange(e.target.checked)} {...rest} />
      {label && (
        <span className={css.text}>
          <span>{label}</span>
          {note && <span className={css.note}>{note}</span>}
        </span>
      )}
    </label>
  );
}
