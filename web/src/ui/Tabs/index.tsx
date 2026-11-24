// Tabs of one block: a bar of names (role tablist) and the panel of the chosen one under it. Only
// the chosen panel is rendered: children is the content for the current value. A tab may carry a
// count (a number or a sum, muted) and a mark — a dot that says something there needs attention
// (said in words by ariaLabel). The bar scrolls sideways when the block is narrower than the names
// (a card on a phone). Arrows, Home and End move between the tabs from the keyboard.

import { type KeyboardEvent, type ReactNode, useId, useRef } from "react";
import { cx } from "@/shared/cx";
import css from "./Tabs.module.scss";

export interface Tab<T extends string> {
  value: T;
  label: ReactNode;
  count?: ReactNode;    // a number or a sum after the name
  mark?: boolean;       // a dot: something here needs attention
  ariaLabel?: string;   // when the name alone says too little (a count, the mark)
}

interface Props<T extends string> {
  tabs: Tab<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;              // of the bar, for screen readers
  className?: string;
  panelClassName?: string;
  children?: ReactNode;       // the panel of the chosen tab
}

export function Tabs<T extends string>({ tabs, value, onChange, label, className, panelClassName, children }: Props<T>) {
  const base = useId();
  const bar = useRef<HTMLDivElement>(null);
  const id = (v: T) => `${base}-${v}`;

  const keys = (ev: KeyboardEvent) => {
    const at = tabs.findIndex((t) => t.value === value);
    const step = { ArrowRight: 1, ArrowLeft: -1 }[ev.key];
    const to = step !== undefined ? (at + step + tabs.length) % tabs.length : ev.key === "Home" ? 0 : ev.key === "End" ? tabs.length - 1 : -1;
    if (to < 0) return;
    ev.preventDefault();
    const next = tabs[to].value;
    onChange(next);
    bar.current?.querySelector<HTMLElement>(`[id="${id(next)}"]`)?.focus();
  };

  return (
    <div className={cx(css.tabs, className)}>
      <div ref={bar} role="tablist" aria-label={label} className={css.bar} onKeyDown={keys}>
        {tabs.map((t) => {
          const on = t.value === value;
          return (
            <button key={t.value} id={id(t.value)} type="button" role="tab" aria-selected={on} aria-controls={on ? `${id(t.value)}-panel` : undefined}
                    aria-label={t.ariaLabel} tabIndex={on ? 0 : -1} className={cx(css.tab, on && css.on)} onClick={() => onChange(t.value)}>
              {t.label}
              {t.count != null && t.count !== false && <span className={css.count}>{t.count}</span>}
              {t.mark && <span className={css.mark} aria-hidden="true" />}
            </button>
          );
        })}
      </div>
      <div id={`${id(value)}-panel`} role="tabpanel" aria-labelledby={id(value)} className={cx(css.panel, panelClassName)}>
        {children}
      </div>
    </div>
  );
}
