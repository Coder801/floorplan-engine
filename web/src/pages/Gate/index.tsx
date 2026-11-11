// Login (service/api/auth.py): until logged in, a login card in the middle (Telegram by phone
// number, Google or an e-mail code; at the bottom a project access code from the studio,
// without an account); on first login, "who are you" in a similar card; an invite link
// (?invite=…) is accepted after login. With login off on the server ({"auth": false},
// locally) the page is open, as before.

import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { acceptInvite, chooseAccountType, devLogin, enterAsVisitor, getInvite, getMe, logout, type Invite, type Me } from "@/shared/auth";
import { cx } from "@/shared/cx";
import ui from "@/shared/styles/ui.module.scss";
import { hideSplash } from "@/shared/splash";
import { BRAND, STAGE } from "@/shared/version";
import { GoogleButton } from "@/ui/GoogleButton";
import { HelpTip } from "@/ui/HelpTip";
import { Logo } from "@/ui/Logo";
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

  if (me === null) return <div className={ui.empty}>{error ?? t("common.loading")}</div>;
  if (!me.auth) return <>{children(null)}</>;

  const run = (f: () => Promise<unknown>) => {
    setBusy(true);
    f().then(refresh).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  const account: Account = {
    name: me.user?.name || me.user?.email || me.user?.phone || me.code?.name || (me.visitor ? t("gate.guest") : ""),
    plan: me.user?.account_type ?? null,
    space: me.user?.space?.kind === "studio" ? me.user.space.name : null,
    firm: me.user?.space?.kind === "studio" ? me.user.space : null,
    visitor: !me.user && !!me.visitor,
    code: !me.user && !!me.code,
    logout: () => run(async () => { await logout(); cleanUrl(); }),
  };

  if (me.user && !me.user.account_type && !token) {
    return (
      <div className={css.gate}>
       <div className={cx(css.card, css.wide)}>
        {brand}
        {firm ? (
          <>
            <header className={css.head}>
              <h1>{t("firm.title")}</h1>
              <p className="muted">{t("firm.note")}</p>
            </header>
            <FirmForm onBack={() => setFirm(false)} onDone={() => void refresh()} />
          </>
        ) : (
          <>
            <header className={css.head}>
              <h1>{t("gate.who")}</h1>
              <p className="muted">{t("gate.whoNote")}</p>
            </header>
            <div className={css.choice}>
              <button disabled={busy} onClick={() => run(() => chooseAccountType("client"))}>
                <b>{t("gate.owner")}</b>
                <span className="muted">{t("gate.ownerNote")}</span>
              </button>
              <button disabled={busy} onClick={() => { setError(null); setFirm(true); }}>
                <b>{t("gate.studio")}</b>
                <span className="muted">{t("gate.studioNote")}</span>
              </button>
            </div>
            {error && <p className={css.error}>{error}</p>}
          </>
        )}
        <span className={css.account}>
          <span className="small muted">{account.name}</span>
          <button onClick={account.logout}>{t("common.logout")}</button>
        </span>
       </div>
      </div>
    );
  }
  if (me.user || me.visitor || me.code) return <>{children(account)}</>;

  const login = `/api/auth/google/login${token ? `?invite=${encodeURIComponent(token)}` : ""}`;
  const ways = [me.telegram, me.google, me.email].filter(Boolean).length;
  const or = <span className={css.or}>{t("gate.or")}</span>;
  return (
    <div className={css.gate}>
     <main className={css.card}>
      {brand}
      <header className={css.head}>
        <div className={css.titleRow}>
          <h1>{t("gate.title")}</h1>
          {ways > 0 && <HelpTip label={t("gate.whyNoPasswords")} text={t("gate.noPasswords")} />}
        </div>
        <p className="muted">{t("gate.subtitle")}</p>
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
      {ways === 0 && <p className="muted">{t("gate.loginOff")}</p>}
      <section className={css.byCode}>
        <h2>{t("gate.code")}</h2>
        <CodeLogin onDone={(project) => {
          if (project) location.hash = encodeURIComponent(project);  // straight into the code's project
          void refresh();
        }} />
      </section>
      {me.dev && (
        <button className={css.dev} disabled={busy} onClick={() => run(devLogin)}>{t("gate.dev")}</button>
      )}
      {me.visitor_allowed && (
        <button className={css.visitor} disabled={busy} onClick={() => run(enterAsVisitor)}>{t("gate.visitor")}</button>
      )}
      {error && <p className={css.error}>{error}</p>}
     </main>
    </div>
  );
}

