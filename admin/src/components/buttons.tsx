// Buttons of the admin, the viewer's approach (web/src/ui/IconButton, Tooltip): a square icon
// button whose label is its accessible name and its tooltip, a text button with an icon, a copy
// button and a dangerous action that asks right where it is. Nothing here changes the size of
// its box: the tooltip and the question float over the page (fixed, shared/place.ts), the copy
// button swaps only its icon, so a table around them never re-lays out.
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes, type FocusEvent as ReactFocusEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type Ref } from "react";
import { popPlace, tipPlace, type Place } from "@/shared/place";
import { Icon, type IconName } from "./icons";
import { css, cx } from "./ui";

export const TIP_DELAY_MS = 400;
export const COPIED_MS = 1500;

type Native = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children">;

/** A tooltip for one button: after TIP_DELAY_MS under the mouse or at once on keyboard focus;
 *  gone on leave, blur, a press and a scroll. The text may change while it is shown. */
function useTip(text: string) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [place, setPlace] = useState<Place | null>(null);
  const tip = useRef<HTMLSpanElement>(null);
  const timer = useRef(0);
  const hide = useCallback(() => { window.clearTimeout(timer.current); setAnchor(null); }, []);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  useLayoutEffect(() => {
    if (!anchor) { setPlace(null); return; }
    setPlace(tipPlace(anchor.getBoundingClientRect(), tip.current?.offsetWidth ?? 0, window.innerWidth, window.innerHeight));
  }, [anchor, text]);
  useEffect(() => {
    if (!anchor) return;
    window.addEventListener("scroll", hide, true);
    return () => window.removeEventListener("scroll", hide, true);
  }, [anchor, hide]);
  const handlers = {
    onPointerEnter: (e: ReactPointerEvent<HTMLButtonElement>) => {
      if (e.pointerType !== "mouse") return;
      const el = e.currentTarget;
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setAnchor(el), TIP_DELAY_MS);
    },
    onPointerLeave: hide,
    onPointerDown: hide,
    onBlur: hide,
    onFocus: (e: ReactFocusEvent<HTMLButtonElement>) => { if (focusVisible(e.currentTarget)) setAnchor(e.currentTarget); },
  };
  const node = anchor && (
    <span ref={tip} className={css.tip} aria-hidden="true" data-tip=""
          style={place ?? { left: 0, top: 0, visibility: "hidden" }}>{text}</span>
  );
  return { handlers, node };
}

// jsdom and old browsers may not know :focus-visible: then any focus shows the tooltip
function focusVisible(el: HTMLElement) {
  try { return el.matches(":focus-visible"); } catch { return true; }
}

/** A square button with only an icon. label is required: the accessible name and the tooltip.
 *  danger paints the icon red (revoke, remove), framed gives it a border (in a dialog). */
export function IconButton({ icon, label, variant, className, type = "button", ref, ...rest }: Native & {
  icon: IconName; label: string; variant?: "danger" | "framed"; ref?: Ref<HTMLButtonElement>;
}) {
  const tip = useTip(label);
  return (
    <>
      <button ref={ref} type={type} aria-label={label} className={cx(css.iconBtn, variant && css[variant], className)}
              {...tip.handlers} {...rest}>
        <Icon name={icon} />
      </button>
      {tip.node}
    </>
  );
}

/** A text button with an icon in front: section actions (Добавить, Выдать, Ссылка), header actions. */
export function Button({ icon, variant, className, type = "button", children, ref, ...rest }: Native & {
  icon?: IconName; variant?: "primary" | "danger"; children: ReactNode; ref?: Ref<HTMLButtonElement>;
}) {
  return (
    <button ref={ref} type={type} className={cx(css.btn, variant && css[variant], className)} {...rest}>
      {icon && <Icon name={icon} />}{children}
    </button>
  );
}

/** Copy a value: the copy icon becomes a check for COPIED_MS in the same box; the label (name and
 *  tooltip) says "Скопировано", and a polite live region announces it. */
export function CopyButton({ value, label = "Скопировать", framed }: { value: string; label?: string; framed?: boolean }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = () => navigator.clipboard.writeText(value).then(() => {
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), COPIED_MS);
  }, () => undefined);
  return (
    <>
      <IconButton icon={copied ? "check" : "copy"} label={copied ? "Скопировано" : label} variant={framed ? "framed" : undefined}
                  className={cx(copied && css.done)} onClick={copy} />
      <span className={css.sr} role="status">{copied ? "Скопировано" : ""}</span>
    </>
  );
}

/** A dangerous action asks right where it is, no modal: the question with [Да] [Нет] floats under
 *  the button (fixed, so the row keeps its size), focus goes to "Нет"; Escape returns focus to the
 *  button, a press outside, a scroll or leaving with Tab closes it. The button is an icon (rows of
 *  a table) or, with text, an icon and the label (header actions). */
export function Confirm({ label, question, onYes, disabled, icon = "ban", text }: {
  label: string; question: string; onYes: () => void; disabled?: boolean; icon?: IconName; text?: boolean;
}) {
  const [place, setPlace] = useState<Place | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const no = useRef<HTMLButtonElement>(null);
  const id = useId();
  const open = place !== null;
  const close = useCallback((back: boolean) => {
    setPlace(null);
    if (back) trigger.current?.focus({ preventScroll: true });
  }, []);
  useEffect(() => {
    if (!open) return;
    no.current?.focus({ preventScroll: true });
    const down = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!box.current?.contains(t) && !trigger.current?.contains(t)) close(false);
    };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") close(true); };
    const away = () => close(false);
    document.addEventListener("pointerdown", down, true);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", away, true);
    window.addEventListener("resize", away);
    return () => {
      document.removeEventListener("pointerdown", down, true);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", away, true);
      window.removeEventListener("resize", away);
    };
  }, [open, close]);
  const toggle = () => {
    if (open) close(false);
    else if (trigger.current) setPlace(popPlace(trigger.current.getBoundingClientRect(), window.innerWidth, window.innerHeight));
  };
  const props = {
    ref: trigger, disabled, onClick: toggle,
    "aria-haspopup": "dialog" as const, "aria-expanded": open, "aria-controls": open ? id : undefined,
  };
  return (
    <>
      {text
        ? <Button icon={icon} variant="danger" {...props}>{label}</Button>
        : <IconButton icon={icon} label={label} variant="danger" {...props} />}
      {place && (
        <div ref={box} id={id} role="dialog" aria-label={question} className={css.pop} style={place}
             onBlur={(e) => {
               // focus left for another control; back to the button is not leaving (its press toggles)
               const to = e.relatedTarget;
               if (to && !e.currentTarget.contains(to) && to !== trigger.current) close(false);
             }}>
          <span className={css.popText}>{question}</span>
          <span className={css.popActions}>
            <button className={css.danger} onClick={() => { close(true); onYes(); }}>Да</button>
            <button ref={no} onClick={() => close(true)}>Нет</button>
          </span>
        </div>
      )}
    </>
  );
}
