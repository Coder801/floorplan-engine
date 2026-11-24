// A provisional value: an amount that is not final yet (material prices, decision 2026-11-12) —
// in the warning yellow with a yellow triangle with "!" after it (the same sign as near the limit in
// ReserveList). label explains why: the tooltip over the whole value and the name of the sign for
// screen readers (role img).

import type { ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./Provisional.module.scss";

interface Props {
  label: string;      // why the value is provisional: tooltip and the accessible name of the sign
  className?: string;
  children: ReactNode;
}

export function Provisional({ label, className, children }: Props) {
  return (
    <span className={cx(css.value, className)} title={label}>
      {children}
      <svg className={css.sign} viewBox="0 0 24 24" role="img" aria-label={label}>
        <path className={css.triangle} d="M12 2.500 23 21.500H1z" />
        <path className={css.mark} d="M10.800 9h2.400l-.5 6.500h-1.400zM12 16.300a1.300 1.300 0 1 0 0 2.600 1.300 1.300 0 0 0 0-2.600z" />
      </svg>
    </span>
  );
}
