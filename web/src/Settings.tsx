// Настройки — шестерёнка в шапке: аккаунт (кто вошёл, «Выйти»), план (тип учётки), тема
// и язык интерфейса (флагами; переводы — позже, i18n)

import { useState } from "react";
import { THEMES, type Theme } from "./consts";
import { cx } from "./cx";
import { LANGUAGES } from "./languages";
import { remember, remembered } from "./palette";
import { usePopover } from "./popover";
import css from "./Settings.module.scss";
import menu from "./styles/menu.module.scss";
import ui from "./styles/ui.module.scss";

// Кто вошёл — из Gate; вход выключен (локальный просмотр) — null
export interface Account {
  name: string;
  plan: "client" | "pro" | null;
  visitor: boolean;
  logout: () => void;
}

const PLAN: Record<string, [string, string]> = {
  client: ["Хозяин квартиры", "один свой проект, можно позвать монтажника"],
  pro: ["Студия или монтажник", "проекты без ограничений, приглашения"],
};
const THEME_SHORT: Record<Theme, string> = { system: "Авто", light: "Светлая", dark: "Тёмная" };

interface Props {
  account: Account | null;
  theme: Theme;
  onTheme: (t: Theme) => void;
}

export function Settings({ account, theme, onTheme }: Props) {
  const { open, toggle, ref } = usePopover<HTMLDivElement>();
  const [plan, planNote] = account?.visitor ? ["Гость", "вход для отладки"]
    : account?.plan ? PLAN[account.plan] : ["Не выбран", "выбирается при первом входе"];
  return (
    <div ref={ref} className={cx(menu.wrap, css.settings)}>
      <button className={css.gear} aria-label="Настройки" title="Настройки" aria-haspopup="dialog"
              aria-expanded={open} onClick={toggle}>
        <GearIcon />
      </button>
      {open && (
        <div className={cx(menu.panel, css.panel)} role="dialog" aria-label="Настройки">
          <section>
            <h3>Аккаунт</h3>
            {account ? (
              <div className={css.row}>
                <span className={css.name}>{account.name}</span>
                <button onClick={account.logout}>Выйти</button>
              </div>
            ) : <p className="small muted">Вход выключен — локальный просмотр</p>}
          </section>
          {account && (
            <section>
              <h3>План</h3>
              <div>{plan}</div>
              <div className="small muted">{planNote}</div>
            </section>
          )}
          <section>
            <h3>Тема</h3>
            <div className={cx(ui.segmented, css.themes)} role="radiogroup" aria-label="Тема">
              {THEMES.map((t) => (
                <button key={t} role="radio" aria-checked={t === theme} className={cx(t === theme && ui.on)}
                        onClick={() => onTheme(t)}>{THEME_SHORT[t]}</button>
              ))}
            </div>
          </section>
          <section>
            <h3>Язык</h3>
            <LanguageSelect />
          </section>
        </div>
      )}
    </div>
  );
}

// Язык: кнопка с флагом и меню языков. Пока язык один — переводы подключаются позже (i18n)
function LanguageSelect() {
  const { open, setOpen, toggle, ref } = usePopover<HTMLDivElement>();
  const [code, setCode] = useState(() => remembered("lang") || LANGUAGES[0].code);
  const current = LANGUAGES.find((l) => l.code === code) ?? LANGUAGES[0];
  const pick = (c: string) => { setCode(c); remember("lang", c); setOpen(false); };
  return (
    <div ref={ref} className={menu.wrap}>
      <button className={css.lang} aria-haspopup="listbox" aria-expanded={open} onClick={toggle}>
        <current.Flag className={css.flag} aria-hidden="true" />
        <span>{current.name}</span>
        <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className={cx(menu.panel, css.langs)} role="listbox" aria-label="Язык">
          {LANGUAGES.map(({ code: c, name, Flag }) => (
            <button key={c} className={menu.item} role="option" aria-selected={c === code} onClick={() => pick(c)}>
              <Flag className={css.flag} aria-hidden="true" />
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
