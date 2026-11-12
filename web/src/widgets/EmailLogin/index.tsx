// E-mail code login (service/api/auth.py, /api/auth/email/*): e-mail → code from the e-mail →
// logged in. No passwords; an invite in the address is accepted by Gate after login, as with Google.

import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { startEmailLogin, verifyEmailLogin } from "@/shared/auth";
import { Button } from "@/ui/Button";
import { Text } from "@/ui/Text";
import { TextField } from "@/ui/TextField";
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

  // Countdown to "Send again"
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
          <TextField id="login-email" label={t("gate.emailLabel")} size="lg" type="email" autoComplete="email" required value={email}
                     placeholder="you@example.com" onChange={(e) => setEmail(e.target.value)} />
          <Button type="submit" variant="primary" size="lg" block disabled={busy || !email.trim()}>{t("gate.getCode")}</Button>
        </>
      ) : (
        <>
          <Text>{t("gate.codeSent", { email: email.trim() })}</Text>
          <TextField id="login-code" label={t("gate.codeLabel")} size="lg" mono inputClassName={css.code}
                     inputMode="numeric" autoComplete="one-time-code" autoFocus value={code} placeholder="000000"
                     onChange={(e) => {
                       const v = codeDigits(e.target.value);
                       setCode(v);
                       if (v.length === CODE_LENGTH && !busy) void verify(v);  // a pasted code logs in right away
                     }} />
          <Button type="submit" variant="primary" size="lg" block disabled={busy || code.length !== CODE_LENGTH}>{t("gate.signIn")}</Button>
          <div className={css.links}>
            <Button variant="link" className={css.link} disabled={busy}
                    onClick={() => { setSent(false); setCode(""); setError(null); }}>{t("gate.changeEmail")}</Button>
            <Button variant="link" className={css.link} disabled={busy || wait > 0} onClick={() => void send()}>
              {wait > 0 ? t("gate.resendIn", { s: wait }) : t("gate.resend")}
            </Button>
          </div>
        </>
      )}
      {error && <Text tone="critical" role="alert">{error}</Text>}
    </form>
  );
}
