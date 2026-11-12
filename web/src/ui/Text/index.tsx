// Text of the type scale: body (14/20), small (12/16, notes and hints), caps (labels), lead
// (16/24, the intro under a page title). tone colours it: muted for secondary text, critical
// for errors, major for warnings, ok for success. A paragraph by default (as="p").

import type { ElementType, ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./Text.module.scss";

interface Props {
  as?: ElementType;
  size?: "lead" | "body" | "small" | "caps";
  tone?: "default" | "muted" | "critical" | "major" | "ok";
  weight?: "regular" | "medium" | "bold";
  mono?: boolean;
  align?: "start" | "center";
  id?: string;
  role?: string;
  className?: string;
  children: ReactNode;
}

export function Text({ as: Tag = "p", size = "body", tone = "default", weight, mono, align, id, role, className, children }: Props) {
  return (
    <Tag id={id} role={role} className={cx(css[size], tone !== "default" && css[tone], weight && css[weight], mono && css.mono, align === "center" && css.center, className)}>
      {children}
    </Tag>
  );
}
