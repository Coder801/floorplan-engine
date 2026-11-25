// One cable of a scheme (BoxScheme, SpliceScheme): a badge of what it goes to, the name and, below
// it, the cable details. A button when the scheme can open its target, plain text otherwise; under
// the cursor or focused it asks the scheme to light it on the sheet (useCableLight)

import type { ReactNode } from "react";
import { cx } from "@/shared/cx";
import css from "./CableLine.module.scss";

interface Props {
  name: string;
  meta?: string | null;     // group, cable, length; none in the simple interface mode
  badge?: ReactNode;        // CableBadge of the target
  lit: boolean;
  onLight: (on: boolean) => void;
  open: (() => void) | null;
  label: string;            // what a click opens
  source?: boolean;         // the incoming cable: no badge, the name in bold
  brief?: boolean;          // the simple interface mode: one line
}

export function CableLine({ name, meta, badge, lit, onLight, open, label, source = false, brief = false }: Props) {
  const props = {
    className: cx(css.line, source && css.source, brief && css.brief, lit && css.on, !!open && css.link),
    onPointerEnter: () => onLight(true), onPointerLeave: () => onLight(false),
  };
  const body = (
    <>
      {badge && <span className={css.mark}>{badge}</span>}
      <span className={css.name} title={name}>{name}</span>
      {meta && <span className={css.meta}>{meta}</span>}
    </>
  );
  return open
    ? <button type="button" {...props} title={label} onClick={open}
              onFocus={() => onLight(true)} onBlur={() => onLight(false)}>{body}</button>
    : <div {...props}>{body}</div>;
}
