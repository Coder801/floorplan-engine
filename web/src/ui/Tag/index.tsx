// A short label: a status, a kind, a file format. soft is a filled one (in a card), outline a
// framed round one (next to a heading), mono a format (PNG, DXF). tone colours the text.

import type { ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./Tag.module.scss";

interface Props {
  variant?: "soft" | "outline" | "mono";
  tone?: "muted" | "default" | "major" | "critical" | "ok" | "accent" | "inherit";   // inherit: the colour comes from outside (st-*)
  title?: string;
  className?: string;
  children: ReactNode;
}

export function Tag({ variant = "soft", tone = "muted", title, className, children }: Props) {
  return <span title={title} className={cx(css.tag, css[variant], tone !== "inherit" && css[tone], className)}>{children}</span>;
}
