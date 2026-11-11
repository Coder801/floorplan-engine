// Notice about the product stage on the first visit: a card over everything saying the service
// is in alpha testing. Shown once per browser and stage (seen.ts); "Got it", Esc or a click on
// the veil close it.

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useFade } from "@/shared/popover";
import { BRAND, STAGE } from "@/shared/version";
import { markNoticeSeen, noticeSeen } from "./seen";
import css from "./AlphaNotice.module.scss";

const POINTS = ["errors", "changes", "projects", "feedback"] as const;

export function AlphaNotice() {
  const { t } = useTranslation();
  const fade = useFade();
  const [first] = useState(() => !noticeSeen(STAGE));
  useEffect(() => { if (first) fade.set(true); }, [first]);
  const open = fade.shown && !fade.closing;
  const ok = useRef<HTMLButtonElement>(null);
  const close = () => { markNoticeSeen(STAGE); fade.set(false); };  // fades out (global.scss), then unmounts

  useEffect(() => {
    if (!open) return;
    ok.current?.focus();
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") { ev.stopPropagation(); close(); }
      if (ev.key === "Tab") { ev.preventDefault(); ok.current?.focus(); }  // the only control in the card
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open]);

  if (!fade.shown) return null;
  return (
    <div className={css.veil} data-veil="" data-closing={fade.closing || undefined} onClick={close}>
      <div className={css.card} data-pop="modal" data-closing={fade.closing || undefined} role="dialog" aria-modal="true" aria-labelledby="alpha-title"
           aria-describedby="alpha-lead" onClick={(ev) => ev.stopPropagation()}>
        <span className={css.badge}>{t(`app.stages.${STAGE}`)}</span>
        <h2 id="alpha-title" className={css.title}>
          <span className={css.brand}>{BRAND}</span> {t("alpha.title")}
        </h2>
        <p id="alpha-lead" className={css.lead}>{t("alpha.lead")}</p>
        <ul className={css.points}>
          {POINTS.map((k) => <li key={k}>{t(`alpha.points.${k}`)}</li>)}
        </ul>
        <button ref={ok} className={css.ok} onClick={close}>{t("alpha.ok")}</button>
        <span className="small muted">{t("alpha.foot")}</span>
      </div>
    </div>
  );
}
