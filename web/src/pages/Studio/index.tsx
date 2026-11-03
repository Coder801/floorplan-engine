// Studio settings over the whole screen (#@studio, a section — #@studio/<section>), opened from
// the gear in the header: sections on the left, the section on the right. "Studio" is the
// firm's profile (name, kind, city, logo) from the account; editing comes later, the fields are
// read-only for now. "Price list · electrical" is the studio's prices of works next to the
// market (widgets/PriceList). Plumbing prices come later.

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { Logo } from "@/ui/Logo";
import { PriceList } from "@/widgets/PriceList";
import type { Account } from "@/widgets/Settings";
import css from "./Studio.module.scss";

export const STUDIO_SECTIONS = ["profile", "prices"] as const;
export type StudioSection = (typeof STUDIO_SECTIONS)[number];

interface Props {
  account: Account | null;     // null — login is off: no firm profile
  section: StudioSection;
  onSection: (s: StudioSection) => void;
  onBack: () => void;
}

export function Studio({ account, section, onSection, onBack }: Props) {
  const { t } = useTranslation();
  const [dirty, setDirty] = useState(false);  // unsaved prices
  const leave = useCallback((go: () => void) => { if (!dirty || confirm(t("prices.leave"))) { setDirty(false); go(); } }, [dirty, t]);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => { if (ev.key === "Escape") leave(onBack); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [leave, onBack]);

  return (
    <div className={css.page} role="dialog" aria-modal="true" aria-labelledby="studio-title">
      <div className={css.inner}>
        <header className={css.head}>
          <button className={css.back} onClick={() => leave(onBack)} aria-label={t("studio.back")} title={t("common.closeEsc")}>←</button>
          <Logo size={36} />
          <div>
            <h1 id="studio-title">{t("studio.title")}</h1>
            {account?.space && <p className="muted">{account.space}</p>}
          </div>
        </header>
        <div className={css.body}>
          <nav className={css.nav} aria-label={t("studio.title")}>
            {STUDIO_SECTIONS.map((s) => (
              <button key={s} className={cx(s === section && css.on)} aria-current={s === section ? "page" : undefined}
                      onClick={() => s !== section && leave(() => onSection(s))}>{t(`studio.sections.${s}`)}</button>
            ))}
            <span className={css.soon}>{t("studio.sections.plumbing")} <i>{t("studio.soon")}</i></span>
          </nav>
          <main className={css.main}>
            {section === "profile" ? <Profile account={account} /> : <PriceList onDirty={setDirty} />}
          </main>
        </div>
      </div>
    </div>
  );
}

// Firm profile: logo, name, kind, city — read-only until editing arrives
function Profile({ account }: { account: Account | null }) {
  const { t } = useTranslation();
  const firm = account?.firm ?? null;
  const name = firm?.name || account?.space || "";
  return (
    <section className={css.profile} aria-labelledby="profile-title">
      <h2 id="profile-title">{t("studio.sections.profile")}</h2>
      {!account && <p className="muted">{t("studio.loginOff")}</p>}
      {account && !firm && <p className="muted">{t("studio.noFirm")}</p>}
      <div className={css.card}>
        <div className={css.logoRow}>
          <div className={css.logo} aria-label={t("studio.logo")}>{name.trim().charAt(0).toUpperCase() || "—"}</div>
          <div>
            <div className={css.label}>{t("studio.logo")}</div>
            <button disabled title={t("studio.later")}>{t("studio.uploadLogo")}</button>
          </div>
        </div>
        <Field label={t("studio.name")} value={name} />
        <Field label={t("studio.kind")} value={firm?.business ? t(`firm.kinds.${firm.business}`) : ""} />
        <Field label={t("studio.city")} value={firm?.city ?? ""} />
        <p className="small muted">{t("studio.later")}</p>
      </div>
    </section>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation();
  return (
    <label className={css.field}>
      <span className={css.label}>{label}</span>
      <input value={value} placeholder={t("studio.empty")} readOnly disabled />
    </label>
  );
}
