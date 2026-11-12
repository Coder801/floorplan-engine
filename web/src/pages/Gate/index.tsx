// Login (service/api/auth.py): until logged in, a login card in the middle (Telegram by phone
// number, Google or an e-mail code; at the bottom a project access code from the studio,
// without an account); on first login, "who are you" in a similar card; an invite link
// (?invite=…) is accepted after login. With login off on the server ({"auth": false},
// locally) the page is open, as before.

import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { acceptInvite, chooseAccountType, devLogin, enterAsVisitor, getInvite, getMe, logout, type Invite, type Me } from "@/shared/auth";
import { cx } from "@/shared/cx";
import { hideSplash } from "@/shared/splash";
import { BRAND, STAGE } from "@/shared/version";
import { Button } from "@/ui/Button";
import { Card } from "@/ui/Card";
import { EmptyState } from "@/ui/EmptyState";
import { GoogleButton } from "@/ui/GoogleButton";
import { Heading } from "@/ui/Heading";
import { HelpTip } from "@/ui/HelpTip";
import { Logo } from "@/ui/Logo";
import { Text } from "@/ui/Text";
import { CodeLogin } from "@/widgets/CodeLogin";
import { EmailLogin } from "@/widgets/EmailLogin";
import { FirmForm } from "@/widgets/FirmForm";
import type { Account } from "@/widgets/Settings";
import { TelegramLogin } from "@/widgets/TelegramLogin";
import css from "./Gate.module.scss";

const ROLES = ["client", "installer", "designer"] as const;
const isRole = (r: string): r is (typeof ROLES)[number] => (ROLES as readonly string[]).includes(r);

const params = () => new URLSearchParams(location.search);

// Remove ?invite and ?auth_error from the address, keeping #project
function cleanUrl() {
  history.replaceState(null, "", `${location.pathname}${location.hash}`);
}

// children receive who is logged in (settings in the header); null if login is off
export function Gate({ children }: { children: (account: Account | null) => ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [invite, setInvite] = useState<Invite | null>(null);
  const [error, setError] = useState<string | null>(() => params().get("auth_error"));
  const [busy, setBusy] = useState(false);
  const [firm, setFirm] = useState(false);  // first login: the firm registration step
  const { t } = useTranslation();
  const token = params().get("invite");

  const refresh = () => getMe().then(setMe).catch((e: Error) => setError(e.message));
  useEffect(() => { void refresh(); }, []);
  useEffect(() => {
    if (!token) return;
    getInvite(token).then(setInvite).catch((e: Error) => setError(e.message));
  }, [token]);
  // Logged in and the address has an invite: accept it
  useEffect(() => {
    if (!token || !me?.user) return;
    acceptInvite(token)
      .then((r) => { cleanUrl(); if (r.project) location.hash = encodeURIComponent(r.project); void refresh(); })
      .catch((e: Error) => { setError(e.message); cleanUrl(); });
  }, [token, me?.user?.id]);

  // The splash leaves when Gate shows its own screen (login, account type, an error); the viewer
  // removes it itself once the projects are loaded
  const own = me === null ? !!error : me.auth && !(me.user || me.visitor || me.code) || (!!me.user && !me.user.account_type && !token);
  useEffect(() => { if (own) hideSplash(); }, [own]);

  // Product mark and name above the form
  const brand = <span className={css.brand}><Logo size={32} /><b>{BRAND}</b><i>{t(`app.stages.${STAGE}`)}</i></span>;

  if (me === null) return <EmptyState>{error ?? t("common.loading")}</EmptyState>;
  if (!me.auth) return <>{children(null)}</>;

  const run = (f: () => Promise<unknown>) => {
    setBusy(true);
    f().then(refresh).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  const account: Account = {
    id: me.user?.id ?? null,
    name: me.user?.name || me.user?.email || me.user?.phone || me.code?.name || (me.visitor ? t("gate.guest") : ""),
    plan: me.user?.account_type ?? null,
    space: me.user?.space?.kind === "studio" ? me.user.space.name : null,
    firm: me.user?.space?.kind === "studio" ? me.user.space : null,
    visitor: !me.user && !!me.visitor,
    code: !me.user && !!me.code,
    feedback: !!me.feedback,
    logout: () => run(async () => { await logout(); cleanUrl(); }),
  };

  if (me.user && !me.user.account_type && !token) {
    return (
      <div className={css.gate}>
       <Card padding="lg" className={cx(css.card, css.wide)}>
        {brand}
        {firm ? (
          <>
            <header className={css.head}>
              <Heading level={1}>{t("firm.title")}</Heading>
              <Text tone="muted">{t("firm.note")}</Text>
            </header>
            <FirmForm onBack={() => setFirm(false)} onDone={() => void refresh()} />
          </>
        ) : (
          <>
            <header className={css.head}>
              <Heading level={1}>{t("gate.who")}</Heading>
              <Text tone="muted">{t("gate.whoNote")}</Text>
            </header>
            <div className={css.choice}>
              <Card as="button" type="button" padding="sm" interactive className={css.option} disabled={busy}
                    onClick={() => run(() => chooseAccountType("client"))}>
                <Heading level={2} size="subheading">{t("gate.owner")}</Heading>
                <Text size="small" tone="muted" as="span">{t("gate.ownerNote")}</Text>
              </Card>
              <Card as="button" type="button" padding="sm" interactive className={css.option} disabled={busy}
                    onClick={() => { setError(null); setFirm(true); }}>
                <Heading level={2} size="subheading">{t("gate.studio")}</Heading>
                <Text size="small" tone="muted" as="span">{t("gate.studioNote")}</Text>
              </Card>
            </div>
            {error && <Text tone="critical" role="alert">{error}</Text>}
          </>
        )}
        <span className={css.account}>
          <Text as="span" size="small" tone="muted">{account.name}</Text>
          <Button size="sm" onClick={account.logout}>{t("common.logout")}</Button>
        </span>
       </Card>
      </div>
    );
  }
  if (me.user || me.visitor || me.code) return <>{children(account)}</>;

  const login = `/api/auth/google/login${token ? `?invite=${encodeURIComponent(token)}` : ""}`;
  const ways = [me.telegram, me.google, me.email].filter(Boolean).length;
  const or = <span className={css.or}>{t("gate.or")}</span>;
  return (
    <div className={css.gate}>
     <Card as="main" padding="lg" className={css.card}>
      {brand}
      <header className={css.head}>
        <div className={css.titleRow}>
          <Heading level={1}>{t("gate.title")}</Heading>
          {ways > 0 && <HelpTip label={t("gate.whyNoPasswords")} text={t("gate.noPasswords")} />}
        </div>
        <Text tone="muted">{t("gate.subtitle")}</Text>
      </header>
      {invite && (
        <p className={css.invite}>
          {t("gate.invited", {
            project: invite.project ?? t("gate.studioProject"),
            role: isRole(invite.role) ? t(`gate.role.${invite.role}`) : invite.role,
          })}{" "}
          {t("gate.acceptInvite")}
        </p>
      )}
      {me.telegram && <TelegramLogin invite={token} onDone={() => void refresh()} />}
      {me.telegram && me.google && or}
      {me.google && <GoogleButton href={login} label={t("gate.google")} />}
      {(me.telegram || me.google) && me.email && or}
      {me.email && <EmailLogin onDone={() => void refresh()} />}
      {ways === 0 && <Text tone="muted">{t("gate.loginOff")}</Text>}
      <section className={css.byCode}>
        <Heading level={2} size="subheading">{t("gate.code")}</Heading>
        <CodeLogin onDone={(project) => {
          if (project) location.hash = encodeURIComponent(project);  // straight into the code's project
          void refresh();
        }} />
      </section>
      {me.dev && (
        <Button size="lg" block className={css.dev} disabled={busy} onClick={() => run(devLogin)}>{t("gate.dev")}</Button>
      )}
      {me.visitor_allowed && (
        <Button size="lg" block disabled={busy} onClick={() => run(enterAsVisitor)}>{t("gate.visitor")}</Button>
      )}
      {error && <Text tone="critical" role="alert">{error}</Text>}
     </Card>
    </div>
  );
}

