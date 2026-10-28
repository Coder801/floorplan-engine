// Вход (service/auth.py): пока не вошли — экран входа; первый вход — выбор «кто вы»;
// ссылка-приглашение (?invite=…) — принять после входа. Вход выключен на сервере
// ({"auth": false}, локально) — страница открыта, как раньше.

import { type ReactNode, useEffect, useState } from "react";
import { acceptInvite, chooseAccountType, enterAsVisitor, getInvite, getMe, logout, type Invite, type Me } from "./auth";
import css from "./Gate.module.scss";
import { Logo } from "./Logo";
import type { Account } from "./Settings";
import ui from "./styles/ui.module.scss";

const ROLE: Record<string, string> = {
  client: "хозяин квартиры",
  installer: "монтажник",
  designer: "проектировщик",
};

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

  if (me === null) return <div className={ui.empty}>{error ?? "Загрузка…"}</div>;
  if (!me.auth) return <>{children(null)}</>;

  const run = (f: () => Promise<unknown>) => {
    setBusy(true);
    f().then(refresh).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  const account: Account = {
    name: me.user?.name || me.user?.email || (me.visitor ? "гость (отладка)" : ""),
    plan: me.user?.account_type ?? null,
    visitor: !me.user && !!me.visitor,
    logout: () => run(async () => { await logout(); cleanUrl(); }),
  };

  if (me.user && !me.user.account_type && !token) {
    return (
      <div className={css.gate}>
        <Logo />
        <h1>Кто вы?</h1>
        <p className="muted">Выбор один раз: от него зависит, что вы увидите.</p>
        <div className={css.choice}>
          <button disabled={busy} onClick={() => run(() => chooseAccountType("client"))}>
            <b>Хозяин квартиры</b>
            <span className="muted">Один свой проект: чертежи, смета, вопросы. Можно позвать монтажника.</span>
          </button>
          <button disabled={busy} onClick={() => run(() => chooseAccountType("pro"))}>
            <b>Студия или монтажник</b>
            <span className="muted">Сколько угодно проектов, приглашения клиентам и монтажникам.</span>
          </button>
        </div>
        {error && <p className={css.error}>{error}</p>}
        <span className={css.account}>
          <span className="small muted">{account.name}</span>
          <button onClick={account.logout}>Выйти</button>
        </span>
      </div>
    );
  }
  if (me.user || me.visitor) return <>{children(account)}</>;

  const login = `/api/auth/google/login${token ? `?invite=${encodeURIComponent(token)}` : ""}`;
  return (
    <div className={css.gate}>
      <Logo />
      <h1>Вход в Штробу</h1>
      {invite && (
        <p>
          Вас пригласили в проект <b>{invite.project ?? "студии"}</b> как {ROLE[invite.role] ?? invite.role}.
          Войдите, чтобы принять приглашение.
        </p>
      )}
      {me.google
        ? <a className={ui.btnLink} href={login}>Войти через Google</a>
        : <p className="muted">Вход через Google ещё не настроен на сервере.</p>}
      {me.visitor_allowed && (
        <button disabled={busy} onClick={() => run(enterAsVisitor)}>Войти как гость (отладка)</button>
      )}
      {error && <p className={css.error}>{error}</p>}
    </div>
  );
}
