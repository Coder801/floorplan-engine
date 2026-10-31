// Вход по коду на почту (service/api/auth.py, /api/auth/email/*): почта → код из письма →
// вход. Без паролей; приглашение из адреса принимает Gate после входа, как у Google.

import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { startEmailLogin, verifyEmailLogin } from "@/shared/auth";
import { CODE_LENGTH, codeDigits, secondsLeft } from "./code";
import css from "./EmailLogin.module.scss";

export function EmailLogin({ onDone }: { onDone: () => void }) {
  const { t, i18n } = useTranslation();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [resendAt, setResendAt] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Обратный отсчёт до «Отправить ещё раз»
  useEffect(() => {
    if (!sent || now >= resendAt) return;
    const timer = setTimeout(() => setNow(Date.now()), 1000);
    return () => clearTimeout(timer);
  }, [sent, now, resendAt]);

  const send = async () => {
    setBusy(true); setError(null);
    try {
      const r = await startEmailLogin(email, i18n.language);
      setSent(true); setCode("");
      setResendAt(Date.now() + r.resend_in * 1000); setNow(Date.now());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const verify = async (value: string) => {
    setBusy(true); setError(null);
    try {
      await verifyEmailLogin(email, value);
      onDone();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!sent) void send();
    else if (code.length === CODE_LENGTH) void verify(code);
  };

  const wait = secondsLeft(resendAt, now);
  return (
    <form className={css.form} onSubmit={submit}>
      {!sent ? (
        <>
          <label htmlFor="login-email">{t("gate.emailLabel")}</label>
          <div className={css.stack}>
            <input id="login-email" type="email" autoComplete="email" required value={email}
                   placeholder="you@example.com" onChange={(e) => setEmail(e.target.value)} />
            <button className={css.primary} type="submit" disabled={busy || !email.trim()}>{t("gate.getCode")}</button>
          </div>
        </>
      ) : (
        <>
          <p className={css.sent}>{t("gate.codeSent", { email: email.trim() })}</p>
          <label htmlFor="login-code">{t("gate.codeLabel")}</label>
          <div className={css.stack}>
            <input id="login-code" className={css.code} inputMode="numeric" autoComplete="one-time-code"
                   autoFocus value={code} placeholder="000000"
                   onChange={(e) => {
                     const v = codeDigits(e.target.value);
                     setCode(v);
                     if (v.length === CODE_LENGTH && !busy) void verify(v);  // вставили код — сразу вход
                   }} />
            <button className={css.primary} type="submit" disabled={busy || code.length !== CODE_LENGTH}>{t("gate.signIn")}</button>
          </div>
          <div className={css.links}>
            <button type="button" className={css.link} disabled={busy}
                    onClick={() => { setSent(false); setCode(""); setError(null); }}>{t("gate.changeEmail")}</button>
            <button type="button" className={css.link} disabled={busy || wait > 0} onClick={() => void send()}>
              {wait > 0 ? t("gate.resendIn", { s: wait }) : t("gate.resend")}
            </button>
          </div>
        </>
      )}
      {error && <p className={css.error} role="alert">{error}</p>}
    </form>
  );
}
