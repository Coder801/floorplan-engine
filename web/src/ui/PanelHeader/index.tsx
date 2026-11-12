// The heading row of a slide-out panel or menu: the title and, on the right, its buttons (pass
// IconButton variant="close"). start puts the buttons before the title (a back arrow).

import type { ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./PanelHeader.module.scss";

interface Props {
  title: ReactNode;
  children?: ReactNode;      // buttons
  start?: ReactNode;         // before the title
  id?: string;               // for aria-labelledby of the panel
  className?: string;
}

export function PanelHeader({ title, children, start, id, className }: Props) {
  return (
    <div className={cx(css.head, className)}>
      {start}
      <h2 id={id} className={css.title}>{title}</h2>
      {children}
    </div>
  );
}
