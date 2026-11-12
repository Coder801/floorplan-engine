// A choice as a card: a radio button hidden inside a framed tile with a title and a description
// (firm kind, how to log in). Put several in a grid inside a fieldset; the same name joins them.

import type { ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./RadioCard.module.scss";

interface Props {
  name: string;
  value: string;
  checked: boolean;
  onChange: (value: string) => void;
  title: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  className?: string;
}

export function RadioCard({ name, value, checked, onChange, title, description, disabled, className }: Props) {
  return (
    <label className={cx(css.card, checked && css.on, disabled && css.disabled, className)}>
      <input type="radio" className={css.input} name={name} value={value} checked={checked} disabled={disabled}
             onChange={() => onChange(value)} />
      <span className={css.title}>{title}</span>
      {description && <span className={css.description}>{description}</span>}
    </label>
  );
}
