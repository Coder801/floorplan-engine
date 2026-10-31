// Настройки — шестерёнка в шапке: аккаунт (кто вошёл, «Выйти»), план (тип учётки), тема
// и язык интерфейса (i18n: украинский, русский, английский; выбор запоминается)

import { useTranslation } from "react-i18next";
import { THEMES, type Theme } from "@/shared/consts";
import { cx } from "@/shared/cx";
import { LANGUAGES, setLanguage } from "@/shared/i18n";
import { usePopover } from "@/shared/popover";
import menu from "@/shared/styles/menu.module.scss";
import ui from "@/shared/styles/ui.module.scss";
import css from "./Settings.module.scss";

// Кто вошёл — из Gate; вход выключен (локальный просмотр) — null
export interface Account {
  name: string;
  plan: "client" | "pro" | null;
  space?: string | null;  // название фирмы (у «Моего ремонта» — нет)
  visitor: boolean;
  logout: () => void;
}


interface Props {
  account: Account | null;
  theme: Theme;
  onTheme: (t: Theme) => void;
}

export function Settings({ account, theme, onTheme }: Props) {
  const { open, toggle, ref } = usePopover<HTMLDivElement>();
  const { t } = useTranslation();
  const plan = account?.visitor ? "guest" : account?.plan ?? "none";
  return (
    <div ref={ref} className={cx(menu.wrap, css.settings)}>
      <button className={css.gear} aria-label={t("settings.title")} title={t("settings.title")} aria-haspopup="dialog"
              aria-expanded={open} onClick={toggle}>
        <GearIcon />
      </button>
      {open && (
        <div className={cx(menu.panel, css.panel)} role="dialog" aria-label={t("settings.title")}>
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
        </div>
      )}
    </div>
  );
}

// Язык интерфейса: кнопка с названием и меню языков; смена — сразу, без перезагрузки
function LanguageSelect() {
  const { open, setOpen, toggle, ref } = usePopover<HTMLDivElement>();
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
        <div className={cx(menu.panel, css.langs)} role="listbox" aria-label={t("settings.language")}>
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
