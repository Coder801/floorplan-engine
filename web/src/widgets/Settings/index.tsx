// Settings, a gear in the header (and on the welcome screen): account (who is logged in, "Log
// out"), plan (account type), "Studio settings" (pages/Studio, studio only), "Leave feedback"
// (widgets/Feedback, when the server takes it), interface mode (simple or engineering, shared/mode.ts; what each shows is a tooltip on its button, ui/Tooltip), theme and interface language (i18n: Ukrainian, Russian, English; the choice is remembered);
// at the bottom the product version and stage with the build number (shared/version.ts)

import { useTranslation } from "react-i18next";
import type { Space } from "@/shared/auth";
import { THEMES, type Theme } from "@/shared/consts";
import { cx } from "@/shared/cx";
import { LANGUAGES, setLanguage } from "@/shared/i18n";
import { UI_MODES, type UiMode } from "@/shared/mode";
import { usePopover } from "@/shared/popover";
import { APP_VERSION, BRAND, BUILD_ID, STAGE } from "@/shared/version";
import menu from "@/shared/styles/menu.module.scss";
import { Button } from "@/ui/Button";
import { Card } from "@/ui/Card";
import { Heading } from "@/ui/Heading";
import { IconButton } from "@/ui/IconButton";
import { Menu } from "@/ui/Menu";
import { MenuItem } from "@/ui/MenuItem";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Text } from "@/ui/Text";
import { useTooltip } from "@/ui/Tooltip";
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
  feedback?: boolean;     // the server takes product feedback (Me.feedback): "Leave feedback"
  logout: () => void;
}


interface Props {
  account: Account | null;
  theme: Theme;
  onTheme: (t: Theme) => void;
  mode: UiMode;
  onMode: (m: UiMode) => void;
  onStudio?: () => void;  // open the studio settings (studio only; no button otherwise)
  onFeedback?: () => void;  // open "Leave feedback" (widgets/Feedback; no button without it)
}

export function Settings({ account, theme, onTheme, mode, onMode, onStudio, onFeedback }: Props) {
  const { open, closing, setOpen, toggle, ref } = usePopover<HTMLDivElement>();
  const { t } = useTranslation();
  const modeTip = useTooltip();
  const plan = account?.visitor ? "guest" : account?.code ? "code" : account?.plan ?? "none";
  return (
    <div ref={ref} className={cx(menu.wrap, css.settings)}>
      <IconButton variant="framed" label={t("settings.title")} aria-haspopup="dialog" aria-expanded={open} onClick={toggle}>
        <GearIcon />
      </IconButton>
      {open && (
        <Menu role="dialog" closing={closing} label={t("settings.title")} className={css.panel}>
          <section>
            <Heading level={3} size="caps">{t("settings.account")}</Heading>
            {account ? (
              <div className={css.row}>
                <span className={css.name}>{account.name}</span>
                <Button size="sm" onClick={account.logout}>{t("common.logout")}</Button>
              </div>
            ) : <Text size="small" tone="muted">{t("settings.loginOff")}</Text>}
          </section>
          {account && (
            <section>
              <Heading level={3} size="caps">{t("settings.plan")}</Heading>
              <Text as="div">{account.space ?? t(`settings.plans.${plan}`)}</Text>
              <Text as="div" size="small" tone="muted">{t(`settings.plans.${plan}Note`)}</Text>
            </section>
          )}
          {onStudio && (
            <section>
              <Card as="button" type="button" padding="sm" interactive className={css.studio} onClick={() => { setOpen(false); onStudio(); }}>
                <Text as="span">{t("settings.studio")}</Text>
                <Text as="span" size="small" tone="muted">{t("settings.studioNote")}</Text>
              </Card>
            </section>
          )}
          {onFeedback && (
            <section>
              <Card as="button" type="button" padding="sm" interactive className={css.studio} onClick={() => { setOpen(false); onFeedback(); }}>
                <Text as="span">{t("settings.feedback")}</Text>
                <Text as="span" size="small" tone="muted">{t("settings.feedbackNote")}</Text>
              </Card>
            </section>
          )}
          <section>
            <Heading level={3} size="caps">{t("settings.mode")}</Heading>
            <SegmentedControl fill label={t("settings.mode")} value={mode} onChange={onMode}
                              options={UI_MODES.map((m) => ({ value: m, label: t(`settings.modes.${m}`), buttonProps: modeTip.on(t(`settings.modes.${m}Note`)) }))} />
            {modeTip.tip}
          </section>
          <section>
            <Heading level={3} size="caps">{t("settings.theme")}</Heading>
            <SegmentedControl fill label={t("settings.theme")} value={theme} onChange={onTheme}
                              options={THEMES.map((th) => ({ value: th, label: t(`settings.themes.${th}`) }))} />
          </section>
          <section>
            <Heading level={3} size="caps">{t("settings.language")}</Heading>
            <LanguageSelect />
          </section>
          <section>
            <Text as="span"><b className={css.brand}>{BRAND}</b> {t("settings.version", { version: APP_VERSION, stage: t(`app.stages.${STAGE}`) })}</Text>
            <Text as="span" size="small" tone="muted">{t("settings.build", { build: BUILD_ID })}</Text>
          </section>
        </Menu>
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
      <Button block className={css.lang} aria-haspopup="listbox" aria-expanded={open} onClick={toggle}>
        <span>{current.name}</span>
        <span aria-hidden="true">▾</span>
      </Button>
      {open && (
        <Menu role="listbox" closing={closing} label={t("settings.language")} className={css.langs}>
          {LANGUAGES.map(({ code: c, name }) => (
            <MenuItem key={c} role="option" selected={c === code} note={c === code ? "✓" : ""} onClick={() => pick(c)}>{name}</MenuItem>
          ))}
        </Menu>
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
