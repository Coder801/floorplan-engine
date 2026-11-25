// What a cable goes to, on the schemes of a junction box and of a flush box (BoxScheme,
// SpliceScheme): the point number on a plate of the group colour, an empty square for the next
// box, a dot for a point without a number

import { cx } from "@/shared/cx";
import type { BoxBranch } from "@/shared/types";
import css from "./CableBadge.module.scss";

interface Props {
  branch: BoxBranch;
  color: string | null;   // group colour (shared/page.ts, groupColors)
  small?: boolean;        // inside a line of text (the joints of SpliceScheme)
}

export function CableBadge({ branch, color, small = false }: Props) {
  const style = color ? { background: color, borderColor: color } : undefined;
  const cls = cx(css.badge, small && css.small);
  if (branch.kind === "box") return <span className={cx(cls, css.toBox)} aria-hidden="true" />;
  if (branch.number == null) return <span className={cx(cls, css.dot)} style={style} aria-hidden="true" />;
  return <span className={cx(cls, "mono")} style={style}>{branch.number}</span>;
}
