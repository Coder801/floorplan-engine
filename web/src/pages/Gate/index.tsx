// Вход (service/api/auth.py): пока не вошли — карточка входа по центру (Google или код на
// почту); первый вход — выбор «кто вы» в такой же карточке;
// ссылка-приглашение (?invite=…) — принять после входа. Вход выключен на сервере
// ({"auth": false}, локально) — страница открыта, как раньше.

import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { acceptInvite, chooseAccountType, devLogin, enterAsVisitor, getInvite, getMe, logout, type Invite, type Me } from "@/shared/auth";
import { cx } from "@/shared/cx";
import ui from "@/shared/styles/ui.module.scss";
import { GoogleButton } from "@/ui/GoogleButton";
import { HelpTip } from "@/ui/HelpTip";
import { Logo } from "@/ui/Logo";
import { EmailLogin } from "@/widgets/EmailLogin";
import { FirmForm } from "@/widgets/FirmForm";
import type { Account } from "@/widgets/Settings";
import css from "./Gate.module.scss";

const ROLES = ["client", "installer", "designer"] as const;
const isRole = (r: string): r is (typeof ROLES)[number] => (ROLES as readonly string[]).includes(r);

const params = () => new URLSearchParams(location.search);

// Убрать ?invite и ?auth_error из адреса, оставив #проект
function cleanUrl() {
  history.replaceState(null, "", `${location.pathname}${location.hash}`);
}

// children получает, кто вошёл (настройки в шапке); вход выключен — null
export function Gate({ children }: { children: (account: Account | null) => ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [invite, setInvite] = useState<Invite | null>(null);
  const [error, setError] = useState<string | null>(() => params().get("auth_error"));
  const [busy, setBusy] = useState(false);
  const [firm, setFirm] = useState(false);  // первый вход: шаг регистрации фирмы
  const { t } = useTranslation();
  const token = params().get("invite");

  const refresh = () => getMe().then(setMe).catch((e: Error) => setError(e.message));
  useEffect(() => { void refresh(); }, []);
  useEffect(() => {
    if (!token) return;
    getInvite(token).then(setInvite).catch((e: Error) => setError(e.message));
  }, [token]);
  // Вошли, а в адресе приглашение — принять
  useEffect(() => {
    if (!token || !me?.user) return;
    acceptInvite(token)
      .then((r) => { cleanUrl(); if (r.project) location.hash = encodeURIComponent(r.project); void refresh(); })
      .catch((e: Error) => { setError(e.message); cleanUrl(); });
  }, [token, me?.user?.id]);

  // Знак и имя продукта над формой
  const brand = <span className={css.brand}><Logo size={32} /><b>{t("gate.brand")}</b></span>;

  if (me === null) return <div className={ui.empty}>{error ?? t("common.loading")}</div>;
  if (!me.auth) return <>{children(null)}</>;

  const run = (f: () => Promise<unknown>) => {
    setBusy(true);
    f().then(refresh).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  const account: Account = {
    name: me.user?.name || me.user?.email || (me.visitor ? t("gate.guest") : ""),
    plan: me.user?.account_type ?? null,
    space: me.user?.space?.kind === "studio" ? me.user.space.name : null,
    visitor: !me.user && !!me.visitor,
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
  if (me.user || me.visitor) return <>{children(account)}</>;

  const login = `/api/auth/google/login${token ? `?invite=${encodeURIComponent(token)}` : ""}`;
  return (
    <div className={css.gate}>
     <main className={css.card}>
      {brand}
      <header className={css.head}>
        <div className={css.titleRow}>
          <h1>{t("gate.title")}</h1>
          {(me.google || me.email) && <HelpTip label={t("gate.whyNoPasswords")} text={t("gate.noPasswords")} />}
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
      {me.google && <GoogleButton href={login} label={t("gate.google")} />}
      {me.google && me.email && <span className={css.or}>{t("gate.or")}</span>}
      {me.email && <EmailLogin onDone={() => void refresh()} />}
      {!me.google && !me.email && <p className="muted">{t("gate.loginOff")}</p>}
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

