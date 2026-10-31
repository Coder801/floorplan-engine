// Значок «?» с подсказкой: открывается наведением, фокусом и кликом (на телефоне — касанием),
// закрывается кликом мимо и Esc. label — название кнопки для чтения с экрана, text — подсказка;
// mark — знак на кнопке («?» или «i»), size — диаметр, px; align — подсказка от значка вправо
// (left: значок у левого края подсказки) или влево (right, по умолчанию)

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
