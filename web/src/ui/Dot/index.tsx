// A colour mark before a label: a round dot for a panel group (the colour of its lines on the
// drawing), a square for a device not on a group line (no colour: the muted text colour).

import { cx } from "@/shared/cx";
import css from "./Dot.module.scss";

interface Props {
  color?: string; // any CSS colour; none means the muted text colour
  shape?: "round" | "square";
  className?: string;
}

export function Dot({ color, shape = "round", className }: Props) {
  return (
    <span
      className={cx(css.dot, css[shape], className)}
      style={color ? { background: color } : undefined}
      aria-hidden="true"
    />
  );
}
