// Root select of the interface: options with icons, which a native <select> cannot show. As wide as
// the widest option (hidden copies in one grid cell), so a choice moves nothing. The list is fixed
// to the screen: a scrolling strip or a button group around it must not clip it.

import { type CSSProperties, type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { cx } from "@/shared/cx";
import { usePopover } from "@/shared/popover";
import menu from "@/shared/styles/menu.module.scss";
import css from "./Select.module.scss";

export interface SelectOption {
  value: string;
  label: string;
  icon?: ReactNode;
}

interface Props {
  options: SelectOption[];
  value: string;
  onChange: (value: string) => void;
  label: string;        // for screen readers
  flat?: boolean;       // inside a button group: no frame of its own
}

const GAP = 6;     // from the button to the list
const MARGIN = 12; // from the list to the screen edge

export function Select({ options, value, onChange, label, flat }: Props) {
  const { open, setOpen, ref } = usePopover<HTMLDivElement>();
  const [place, setPlace] = useState<CSSProperties>({});
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const current = options.find((o) => o.value === value) ?? options[0];

  useEffect(() => {
    if (open) list.current?.querySelector<HTMLElement>("[aria-selected='true']")?.focus();
  }, [open]);

  const toggle = () => {
    const box = button.current!.getBoundingClientRect();
    const top = box.bottom + GAP;
    setPlace({ left: box.left, top, minWidth: box.width, maxHeight: innerHeight - top - MARGIN });
    setOpen(!open);
  };
  const pick = (v: string) => { onChange(v); setOpen(false); button.current?.focus(); };
  const arrows = (ev: KeyboardEvent) => {
    const step = { ArrowDown: 1, ArrowUp: -1 }[ev.key];
    if (!step) return;
    ev.preventDefault();
    const items = [...list.current!.querySelectorAll<HTMLElement>("[role='option']")];
    const at = items.indexOf(document.activeElement as HTMLElement);
    items[(at + step + items.length) % items.length]?.focus();
  };

  return (
    <div ref={ref} className={css.select}>
      <button ref={button} className={cx(css.button, flat && css.flat)} aria-label={label}
              aria-haspopup="listbox" aria-expanded={open} onClick={toggle}>
        <span className={css.face}>{current?.icon}{current?.label}</span>
        {options.map((o) => <span key={o.value} className={cx(css.face, css.ghost)}>{o.icon}{o.label}</span>)}
        <span className={css.arrow} aria-hidden="true">▾</span>
      </button>
      {open && (
        <div ref={list} className={cx(menu.panel, css.list)} style={place} role="listbox" aria-label={label} onKeyDown={arrows}>
          {options.map((o) => (
            <button key={o.value} className={menu.item} role="option" aria-selected={o.value === value} onClick={() => pick(o.value)}>
              {o.icon ?? <span />}
              {o.label}
              <span className={menu.note}>{o.value === value ? "✓" : ""}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
