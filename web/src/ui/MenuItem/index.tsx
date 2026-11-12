// A menu row: icon | label | note on the right (a format, a shortcut, a tick). A button, or a
// link with href (a download). role menuitem by default; option in a listbox.

import type { MouseEvent, ReactNode } from "react";
import menu from "@/shared/styles/menu.module.scss";

interface Props {
  children: ReactNode;
  icon?: ReactNode;
  note?: ReactNode;
  onClick?: (ev: MouseEvent) => void;
  disabled?: boolean;
  href?: string;
  download?: string;
  role?: "menuitem" | "option" | "menuitemradio";
  selected?: boolean;
}

export function MenuItem({ children, icon, note, onClick, disabled, href, download, role = "menuitem", selected }: Props) {
  const body = <>{icon ?? <span />}<span>{children}</span><span className={menu.note}>{note}</span></>;
  if (href && !disabled) {
    return <a className={menu.item} role={role} href={href} download={download} onClick={onClick}>{body}</a>;
  }
  return (
    <button type="button" className={menu.item} role={role} disabled={disabled} onClick={onClick}
            aria-selected={role === "option" ? !!selected : undefined}
            aria-checked={role === "menuitemradio" ? !!selected : undefined}>
      {body}
    </button>
  );
}
