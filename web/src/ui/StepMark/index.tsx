// The state of a step in a list of steps: a plain check when it is decided, a short dash when it
// is still open. Not a ring: a ring reads as a radio button. Used in the wizard steps and in
// "What is decided" on the overview.

import { cx } from "@/shared/cx";
import css from "./StepMark.module.scss";

interface Props {
  done: boolean;
  label?: string;  // for screen readers; none: the mark is decoration next to the step name
  className?: string;
}

export function StepMark({ done, label, className }: Props) {
  return (
    <span className={cx(css.mark, className)} {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}>
      {done ? (
        <svg className={css.check} viewBox="0 0 16 16" aria-hidden="true">
          <path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : <span className={css.dash} />}
    </span>
  );
}
