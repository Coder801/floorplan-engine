// A dropdown menu panel under its button (Download, settings): put it and the button in one
// position: relative wrapper with usePopover's ref; open/closing come from usePopover. Items are
// MenuItem. align puts the panel under the right (default) or the left edge of the button.

import type { CSSProperties, ReactNode } from "react";
import { cx } from "@/shared/cx";
import menu from "@/shared/styles/menu.module.scss";
import css from "./Menu.module.scss";

interface Props {
  children: ReactNode;
  closing?: boolean;
  label?: string;
  role?: "menu" | "listbox" | "dialog";
  align?: "left" | "right";
  minWidth?: number;
  className?: string;
  style?: CSSProperties;
}

export function Menu({ children, closing, label, role = "menu", align = "right", minWidth, className, style }: Props) {
  return (
    <div className={cx(menu.panel, align === "left" && css.left, className)} data-pop="" data-closing={closing || undefined}
         role={role} aria-label={label} style={minWidth ? { minWidth, ...style } : style}>
      {children}
    </div>
  );
}
