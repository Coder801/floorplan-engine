// Layout of blocks with even space between them: the vertical rhythm. gap is a step of the 4px
// spacing grid (--space-N: 1 = 4px, 2 = 8, 3 = 12, 4 = 16, 5 = 20, 6 = 24, 8 = 32, 10 = 40).
// Children have no margins of their own (global.scss), so the gap is the only space.
// direction row lays them in a line (wraps by default), e.g. the buttons of a form.

import type { ElementType, HTMLAttributes, ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./Stack.module.scss";

const cap = <T extends string>(s: T) => (s[0].toUpperCase() + s.slice(1)) as Capitalize<T>;

export type Space = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 8 | 10;

interface Props extends HTMLAttributes<HTMLElement> {
  as?: ElementType;
  gap?: Space;
  direction?: "column" | "row";
  align?: "start" | "center" | "end" | "stretch" | "baseline";
  justify?: "start" | "center" | "end" | "between";
  wrap?: boolean;
  children?: ReactNode;
}

export function Stack({ as: Tag = "div", gap = 3, direction = "column", align, justify, wrap = true, className, style, children, ...rest }: Props) {
  return (
    <Tag className={cx(css[direction], align && css[`align${cap(align)}`], justify && css[`justify${cap(justify)}`], direction === "row" && !wrap && css.nowrap, className)}
         style={{ gap: gap ? `var(--space-${gap})` : 0, ...style }} {...rest}>
      {children}
    </Tag>
  );
}
