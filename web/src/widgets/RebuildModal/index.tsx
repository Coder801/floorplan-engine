// Project rebuild (wiring variant change, saving route edits): the interface is blocked by a
// modal with an icon until the server returns the new build. Clicks are blocked by the veil,
// Tab and Esc are intercepted.

import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import css from "./RebuildModal.module.scss";

const KEYS = [0, 1, 2, 3, 4, 5, 6, 7, 8];

export function RebuildModal() {
  const { t } = useTranslation();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    box.current?.focus();
    const lock = (ev: KeyboardEvent) => {
      if (ev.key === "Tab" || ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); }
    };
    window.addEventListener("keydown", lock, true);
    return () => { window.removeEventListener("keydown", lock, true); prev?.focus?.(); };
  }, []);
  return (
    <div className={css.veil} data-veil="">
      <div ref={box} className={css.modal} data-pop="modal" role="alertdialog" aria-modal="true" aria-busy="true"
           aria-labelledby="rebuild-title" tabIndex={-1}>
        {/* Calculator: body, screen and 3×3 buttons pulsing in a diagonal wave */}
        <svg className={css.icon} viewBox="0 0 80 100" width="64" height="80" fill="none" stroke="currentColor"
             strokeWidth="2.5" aria-hidden="true">
          <rect x="3" y="3" width="74" height="94" rx="10" />
          <rect x="11" y="11" width="58" height="22" rx="4" />
          {KEYS.map((i) => (
            <circle key={i} cx={20 + 20 * (i % 3)} cy={50 + 17 * Math.floor(i / 3)} r="5.5" className={css.key} />
          ))}
        </svg>
        <b id="rebuild-title">{t("rebuild.title")}</b>
        <span className="small muted">{t("rebuild.note")}</span>
      </div>
    </div>
  );
}
