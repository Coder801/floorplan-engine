// A heading. level is the document outline (h1–h4: one h1 per screen, no skipped levels); size is
// the look from the type scale, by default the level's own: 1 title, 2 heading, 3 subheading, 4
// caps. A section label in capitals at level 3 is size="caps". display is the welcome screen only.

import type { ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./Heading.module.scss";

export type HeadingSize = "display" | "title" | "heading" | "subheading" | "caps";
const BY_LEVEL: Record<1 | 2 | 3 | 4, HeadingSize> = { 1: "title", 2: "heading", 3: "subheading", 4: "caps" };

interface Props {
  level: 1 | 2 | 3 | 4;
  size?: HeadingSize;
  muted?: boolean;
  id?: string;
  className?: string;
  children: ReactNode;
}

export function Heading({ level, size = BY_LEVEL[level], muted, id, className, children }: Props) {
  const Tag = `h${level}` as const;
  return <Tag id={id} className={cx(css[size], muted && css.muted, className)}>{children}</Tag>;
}
