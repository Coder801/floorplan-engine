// A "?" icon with a tooltip: opens on hover, focus and click (tap on a phone), closes on a
// click outside and Esc. label is the button name for screen readers, text is the tooltip;
// mark is the sign on the button ("?" or "i"), size the diameter in px; align places the
// tooltip to the right of the icon (left: the icon at the tooltip's left edge) or to the left
// (right, the default)

import { useId, useState } from "react";
import { cx } from "@/shared/cx";
import { usePopover } from "@/shared/popover";
import css from "./HelpTip.module.scss";

interface Props { label: string; text: string; mark?: string; size?: number; align?: "left" | "right" }

export function HelpTip({ label, text, mark = "?", size = 24, align = "right" }: Props) {
  const { open, setOpen, toggle, ref } = usePopover<HTMLSpanElement>();
  const [hover, setHover] = useState(false);
  const id = useId();
  const shown = open || hover;
  return (
    <span ref={ref} className={css.wrap}
          onPointerEnter={(e) => e.pointerType === "mouse" && setHover(true)}
          onPointerLeave={() => setHover(false)}>
      <button type="button" className={css.button} aria-label={label} aria-expanded={shown}
              style={{ width: size, height: size, fontSize: Math.round(size * 0.55) }}
              aria-describedby={shown ? id : undefined} onClick={toggle}
              onBlur={() => setOpen(false)}>
        {mark}
      </button>
      {shown && <span id={id} role="tooltip" className={cx(css.tip, align === "left" && css.left)}>{text}</span>}
    </span>
  );
}
