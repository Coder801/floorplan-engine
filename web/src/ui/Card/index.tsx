// A card: a framed block of content. surface is on the page background (the raised colour),
// panel uses the panel colour (project cards). padding is the inner space on the 4px grid;
// interactive adds hover and focus (a card that is a button or a link: pass as="button"),
// selected the highlighted frame. Content inside is laid out by the caller (Stack).

import type { ElementType, HTMLAttributes, ReactNode, Ref } from "react";
import { cx } from "@/shared/cx";
import css from "./Card.module.scss";

const PAD = { none: "padNone", sm: "padSm", md: "padMd", lg: "padLg" } as const;

interface Props extends HTMLAttributes<HTMLElement> {
  as?: ElementType;
  variant?: "surface" | "panel";
  padding?: "none" | "sm" | "md" | "lg";   // 0, 12, 20, 32 px
  interactive?: boolean;
  selected?: boolean;
  children?: ReactNode;
  ref?: Ref<HTMLElement>;
  type?: "button" | "submit";
  disabled?: boolean;
}

export function Card({ as: Tag = "div", variant = "surface", padding = "md", interactive, selected, className, children, ref, ...rest }: Props) {
  return (
    <Tag ref={ref} className={cx(css.card, css[variant], css[PAD[padding]], interactive && css.interactive, selected && css.selected, className)} {...rest}>
      {children}
    </Tag>
  );
}
