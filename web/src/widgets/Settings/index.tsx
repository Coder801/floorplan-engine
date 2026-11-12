// Settings, a gear in the header (and on the welcome screen): account (who is logged in, "Log
// out"), plan (account type), "Studio settings" (pages/Studio, studio only), interface mode (simple or engineering, shared/mode.ts; what each shows is a tooltip on its button, ui/Tooltip), theme and interface language (i18n: Ukrainian, Russian, English; the choice is remembered);
// at the bottom the product version and stage with the build number (shared/version.ts)

import { useTranslation } from "react-i18next";
import type { Space } from "@/shared/auth";
import { THEMES, type Theme } from "@/shared/consts";
import { cx } from "@/shared/cx";
import { LANGUAGES, setLanguage } from "@/shared/i18n";
import { UI_MODES, type UiMode } from "@/shared/mode";
import { usePopover } from "@/shared/popover";
import { useTooltip } from "@/ui/Tooltip";
import { APP_VERSION, BRAND, BUILD_ID, STAGE } from "@/shared/version";
import menu from "@/shared/styles/menu.module.scss";
import ui from "@/shared/styles/ui.module.scss";
import css from "./Settings.module.scss";

// Who is logged in, from Gate; null if login is off (local viewing)
export interface Account {
  id?: string | null;     // the user id (none for a code or the guest): own task photos are deleted by their author
  name: string;
  plan: "client" | "pro" | null;
  space?: string | null;  // firm name ("Мой ремонт" has none)
  firm?: Space | null;    // the firm's profile for the studio settings (kind "studio" only)
  visitor: boolean;
  code?: boolean;         // logged in by a project access code (no account)
  logout: () => void;
}


interface Props {
  account: Account | null;
  theme: Theme;
  onTheme: (t: Theme) => void;
  mode: UiMode;
  onMode: (m: UiMode) => void;
  onStudio?: () => void;  // open the studio settings (studio only; no button otherwise)
}

export function Settings({ account, theme, onTheme, mode, onMode, onStudio }: Props) {
  const { open, closing, setOpen, toggle, ref } = usePopover<HTMLDivElement>();
  const { t } = useTranslation();
  const modeTip = useTooltip();
  const plan = account?.visitor ? "guest" : account?.code ? "code" : account?.plan ?? "none";
  return (
    <div ref={ref} className={cx(menu.wrap, css.settings)}>
      <button className={css.gear} aria-label={t("settings.title")} title={t("settings.title")} aria-haspopup="dialog"
              aria-expanded={open} onClick={toggle}>
        <GearIcon />
      </button>
      {open && (
        <div className={cx(menu.panel, css.panel)} data-pop="" data-closing={closing || undefined} role="dialog" aria-label={t("settings.title")}>
          <section>
            <h3>{t("settings.account")}</h3>
            {account ? (
              <div className={css.row}>
                <span className={css.name}>{account.name}</span>
                <button onClick={account.logout}>{t("common.logout")}</button>
              </div>
            ) : <p className="small muted">{t("settings.loginOff")}</p>}
          </section>
          {account && (
            <section>
              <h3>{t("settings.plan")}</h3>
              <div>{account.space ?? t(`settings.plans.${plan}`)}</div>
              <div className="small muted">{t(`settings.plans.${plan}Note`)}</div>
            </section>
          )}
          {onStudio && (
            <section>
              <button className={css.studio} onClick={() => { setOpen(false); onStudio(); }}>
                <span>{t("settings.studio")}</span>
                <span className="small muted">{t("settings.studioNote")}</span>
              </button>
            </section>
          )}
          <section>
            <h3>{t("settings.mode")}</h3>
            <div className={cx(ui.segmented, css.themes)} role="radiogroup" aria-label={t("settings.mode")}>
              {UI_MODES.map((m) => (
                <button key={m} role="radio" aria-checked={m === mode} className={cx(m === mode && ui.on)}
                        {...modeTip.on(t(`settings.modes.${m}Note`))}
                        onClick={() => onMode(m)}>{t(`settings.modes.${m}`)}</button>
              ))}
            </div>
            {modeTip.tip}
          </section>
          <section>
            <h3>{t("settings.theme")}</h3>
            <div className={cx(ui.segmented, css.themes)} role="radiogroup" aria-label={t("settings.theme")}>
              {THEMES.map((th) => (
                <button key={th} role="radio" aria-checked={th === theme} className={cx(th === theme && ui.on)}
                        onClick={() => onTheme(th)}>{t(`settings.themes.${th}`)}</button>
              ))}
            </div>
          </section>
          <section>
            <h3>{t("settings.language")}</h3>
            <LanguageSelect />
          </section>
          <section className={css.about}>
            <span><b className={css.brand}>{BRAND}</b> {t("settings.version", { version: APP_VERSION, stage: t(`app.stages.${STAGE}`) })}</span>
            <span className="small muted">{t("settings.build", { build: BUILD_ID })}</span>
          </section>
        </div>
      )}
    </div>
  );
}

// Interface language: a button with the name and a language menu; switches right away, no reload
function LanguageSelect() {
  const { open, closing, setOpen, toggle, ref } = usePopover<HTMLDivElement>();
  const { t, i18n } = useTranslation();
  const code = i18n.language;
  const current = LANGUAGES.find((l) => l.code === code) ?? LANGUAGES[0];
  const pick = (c: (typeof LANGUAGES)[number]["code"]) => { setLanguage(c); setOpen(false); };
  return (
    <div ref={ref} className={menu.wrap}>
      <button className={css.lang} aria-haspopup="listbox" aria-expanded={open} onClick={toggle}>
        <span>{current.name}</span>
        <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className={cx(menu.panel, css.langs)} data-pop="" data-closing={closing || undefined} role="listbox" aria-label={t("settings.language")}>
          {LANGUAGES.map(({ code: c, name }) => (
            <button key={c} className={menu.item} role="option" aria-selected={c === code} onClick={() => pick(c)}>
              {name}
              <span className={menu.note}>{c === code ? "✓" : ""}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function GearIcon() {
  return (
    <svg className={css.icon} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </svg>
  );
}
