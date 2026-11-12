// Segments: one choice out of a few, side by side (sheets in the header, feedback kind, model
// files). role radiogroup, so arrows and screen readers see one choice. fill stretches the
// segments over the width in equal columns; size lg is the phone target.

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./SegmentedControl.module.scss";

export interface Segment<T extends string> {
  value: T;
  label: ReactNode;
  title?: string;       // tooltip
  ariaLabel?: string;   // when the label is not enough (a count badge)
  disabled?: boolean;
  buttonProps?: ButtonHTMLAttributes<HTMLButtonElement>;  // e.g. the handlers of useTooltip
}

interface Props<T extends string> {
  options: Segment<T>[];
  value: T | null;
  onChange: (value: T) => void;
  label: string;        // for screen readers
  fill?: boolean;
  size?: "md" | "lg";
  className?: string;
}

export function SegmentedControl<T extends string>({ options, value, onChange, label, fill, size = "md", className }: Props<T>) {
  return (
    <div role="radiogroup" aria-label={label} className={cx(css.segmented, fill && css.fill, size === "lg" && css.lg, className)}
         style={fill ? { gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` } : undefined}>
      {options.map((o) => (
        <button key={o.value} {...o.buttonProps} type="button" role="radio" aria-checked={o.value === value} title={o.title} aria-label={o.ariaLabel}
                disabled={o.disabled} className={cx(css.segment, o.value === value && css.on)}
                onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
