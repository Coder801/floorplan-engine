// In place of a drawing, a list or panel content when there is nothing to show (or it is still
// loading): a muted text in the middle and, if any, an action under it.

import type { ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./EmptyState.module.scss";

interface Props {
  children: ReactNode;
  action?: ReactNode;
  compact?: boolean;       // inside a panel: less space around
  className?: string;
}

export function EmptyState({ children, action, compact, className }: Props) {
  return (
    <div className={cx(css.empty, compact && css.compact, className)}>
      <div>{children}</div>
      {action}
    </div>
  );
}
