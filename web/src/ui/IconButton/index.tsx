// A square button with only an icon or a sign: close cross, arrows, "+", menu. label is required:
// it is the name for screen readers and the tooltip. close is the × of a card, panel or dialog;
// round is a small round one over a picture (remove a photo).

import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";
import { cx } from "@/shared/cx";
import css from "./IconButton.module.scss";

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  label: string;
  children?: ReactNode;          // the icon; the close variant draws × itself
  variant?: "bare" | "framed" | "close" | "round";
  size?: "sm" | "md" | "lg";     // 24, 36, 44 px
  pressed?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

export function IconButton({ label, children, variant = "bare", size = "md", pressed, className, type = "button", title, ref, ...rest }: Props) {
  return (
    <button ref={ref} type={type} aria-label={label} title={title ?? label} aria-pressed={pressed}
            className={cx(css.button, variant !== "bare" && css[variant], css[size], pressed && css.pressed, className)} {...rest}>
      {variant === "close" && !children ? <span aria-hidden="true">×</span> : children}
    </button>
  );
}
