// A group of buttons over the drawing (3D, edit, systems, pagers): one pixel frame as a tray and
// flat entries inside. The group is its own element, not ui/Button in a frame (decision
// 2026-11-14): an entry is GroupButton — no frame, corner or clip of its own, so a badge can
// stick out of it. Other children: a text (span, e.g. a page counter) or Select flat.

import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode, Ref } from "react";
import { cx } from "@/shared/cx";
import css from "./ButtonGroup.module.scss";

interface Props extends HTMLAttributes<HTMLDivElement> {
  label?: string;       // for screen readers
  children: ReactNode;
}

export function ButtonGroup({ label, children, className, ...rest }: Props) {
  return <div role="group" aria-label={label} className={cx(css.group, className)} {...rest}>{children}</div>;
}

interface ItemProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  pressed?: boolean;    // a toggle: undefined means not a toggle
  signal?: boolean;     // the action that changes data (save): the marking yellow
  badge?: ReactNode;    // a number on the corner; hidden from screen readers — say it in aria-label
  ref?: Ref<HTMLButtonElement>;
}

export function GroupButton({ pressed, signal, badge, className, children, type = "button", ...rest }: ItemProps) {
  return (
    <button type={type} aria-pressed={pressed} className={cx(css.item, pressed && css.pressed, signal && css.signal, className)} {...rest}>
      {children}
      {badge != null && badge !== false && <span className={css.badge} aria-hidden="true">{badge}</span>}
    </button>
  );
}
