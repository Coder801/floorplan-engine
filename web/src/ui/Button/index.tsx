// The interface button. variant: default (frame on the raised background), primary (accent fill:
// the one main action of a form or dialog), bare (no frame: arrows, toolbar entries), link (looks
// like a text link), danger (a destructive action, red text in the default frame). size md is the
// desktop control height, lg the phone and form one (44px, a finger target), sm the compact one in
// segments. pressed is a toggle (aria-pressed, accent fill). With href it is a link that looks like
// a button (download, log in). All other props go to the element.

import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode, Ref } from "react";
import { cx } from "@/shared/cx";
import css from "./Button.module.scss";

export type ButtonVariant = "default" | "primary" | "bare" | "link" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

interface Own {
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;      // the whole width of the container
  pressed?: boolean;    // a toggle: undefined means not a toggle
  icon?: ReactNode;     // before the label
  children?: ReactNode;
  className?: string;
}

type AsButton = Own & Omit<ButtonHTMLAttributes<HTMLButtonElement>, keyof Own> & { href?: undefined; ref?: Ref<HTMLButtonElement> };
type AsLink = Own & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, keyof Own> & { href: string; ref?: Ref<HTMLAnchorElement> };
export type ButtonProps = AsButton | AsLink;


export function Button(props: ButtonProps) {
  const { variant, size, block, pressed, icon, children, className, ...rest } = props;
  const cls = cx(css.button, variant && variant !== "default" && css[variant], css[size ?? "md"], block && css.block, pressed && css.pressed, className);
  const body = <>{icon && <span className={css.icon} aria-hidden="true">{icon}</span>}{children}</>;
  if (rest.href !== undefined) {
    const { ref, ...a } = rest as AsLink;
    return <a ref={ref} className={cls} {...a}>{body}</a>;
  }
  const { ref, type = "button", ...b } = rest as AsButton;
  return <button ref={ref} type={type} className={cls} aria-pressed={pressed} {...b}>{body}</button>;
}
