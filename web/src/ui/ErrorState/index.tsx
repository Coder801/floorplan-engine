// In place of a drawing or panel content when it failed: the message in the error colour, line
// breaks kept (a server message may have several lines), and, if any, an action under it.

import type { ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./ErrorState.module.scss";

export function ErrorState({ children, action, className }: { children: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cx(css.error, className)} role="alert">
      <div>{children}</div>
      {action}
    </div>
  );
}
