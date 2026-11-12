// Buttons in one frame with dividers: the drawing options (3D, edit, zoom). Children are Button
// with variant="bare" (or IconButton, Select flat); the group draws the frame and the dividers.

import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./ButtonGroup.module.scss";

interface Props extends HTMLAttributes<HTMLDivElement> {
  label?: string;       // for screen readers
  children: ReactNode;
}

export function ButtonGroup({ label, children, className, ...rest }: Props) {
  return <div role="group" aria-label={label} className={cx(css.group, className)} {...rest}>{children}</div>;
}
