// A dialog over everything, in a portal: a veil and a card in the middle; on a phone the card sits
// at the bottom (a sheet). Esc and a click on the veil call onClose (closeOnVeil false keeps a
// half-filled form from closing by a miss); without onClose it cannot be closed (a blocking
// "wait"). Tab stays inside the card; the card takes focus on open (a child may move it to a
// field) and gives it back on close. The caller lays out the content (Heading, Stack, buttons).

import { useEffect, useRef, type ClipboardEvent, type FormEvent, type ReactNode, type Ref } from "react";
import { createPortal } from "react-dom";
import { cx } from "@/shared/cx";
import css from "./Modal.module.scss";

const FOCUSABLE = "button:not(:disabled), textarea:not(:disabled), input:not([type=file]):not(:disabled), select, [href], [tabindex]:not([tabindex='-1'])";

interface Props {
  children: ReactNode;
  onClose?: () => void;
  closeOnVeil?: boolean;
  size?: "sm" | "md" | "lg";          // 340, 480, 720 px
  role?: "dialog" | "alertdialog";
  labelledBy?: string;
  describedBy?: string;
  label?: string;                     // when there is no heading to point to
  busy?: boolean;
  closing?: boolean;                  // fading out (useFade): no clicks, the global fade-out runs
  as?: "div" | "form";
  onSubmit?: (ev: FormEvent<HTMLFormElement>) => void;
  onPaste?: (ev: ClipboardEvent) => void;
  className?: string;
  ref?: Ref<HTMLElement>;
}

export function Modal({ children, onClose, closeOnVeil = true, size = "md", role = "dialog", labelledBy, describedBy, label,
  busy, closing, as = "div", onSubmit, onPaste, className, ref }: Props) {
  const card = useRef<HTMLElement | null>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    card.current?.focus();
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        ev.preventDefault(); ev.stopPropagation();
        close.current?.();
        return;
      }
      if (ev.key !== "Tab" || !card.current) return;
      const all = [...card.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (!all.length) { ev.preventDefault(); return; }
      const first = all[0], last = all[all.length - 1];
      const inside = card.current.contains(document.activeElement);
      if (ev.shiftKey && (document.activeElement === first || !inside)) { ev.preventDefault(); last.focus(); }
      else if (!ev.shiftKey && (document.activeElement === last || !inside)) { ev.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKey, true);
    return () => { window.removeEventListener("keydown", onKey, true); before?.focus?.(); };
  }, []);

  const setRef = (el: HTMLElement | null) => {
    card.current = el;
    if (typeof ref === "function") ref(el);
    else if (ref) ref.current = el;
  };
  const Tag = as;
  return createPortal(
    <div className={cx(css.veil, !onClose && css.locked)} data-veil="" data-closing={closing || undefined} onClick={() => { if (closeOnVeil) onClose?.(); }}>
      <Tag ref={setRef as never} className={cx(css.card, css[size], className)} data-pop="modal" data-closing={closing || undefined} role={role} aria-modal="true"
           aria-labelledby={labelledBy} aria-describedby={describedBy} aria-label={label} aria-busy={busy || undefined}
           tabIndex={-1} onClick={(ev: React.MouseEvent) => ev.stopPropagation()} onSubmit={onSubmit as never} onPaste={onPaste}>
        {children}
      </Tag>
    </div>,
    document.body,
  );
}
