// A provisional value: an amount that is not final yet (material prices, decision 2026-11-12) —
// in the warning yellow with a "!" after it. label explains why: the tooltip over the whole value
// and the name of the "!" for screen readers (role img), so the sign is not read as plain text.

import type { ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./Provisional.module.scss";

interface Props {
  label: string;      // why the value is provisional: tooltip and the accessible name of the "!"
  className?: string;
  children: ReactNode;
}

export function Provisional({ label, className, children }: Props) {
  return (
    <span className={cx(css.value, className)} title={label}>
      {children}
      <span className={css.sign} role="img" aria-label={label}>!</span>
    </span>
  );
}
