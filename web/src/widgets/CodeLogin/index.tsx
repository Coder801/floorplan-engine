// Вход по коду доступа к проекту (service/api/auth.py, /api/auth/code): студия дала код
// «XXXX-XXXX» — человек вводит его и смотрит этот один проект без учётки. Ошибка (код не
// подходит, истёк, слишком много попыток) — под полем, текст с сервера.

import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { loginByCode } from "@/shared/auth";
import { ACCESS_CODE_LENGTH, accessCodeChars, formatAccessCode } from "./code";
import css from "./CodeLogin.module.scss";

export function CodeLogin({ onDone }: { onDone: (project: string | null) => void }) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = accessCodeChars(code).length === ACCESS_CODE_LENGTH;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready || busy) return;
    setBusy(true); setError(null);
    try {
      const r = await loginByCode(code);
      onDone(r.project);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <form className={css.form} onSubmit={(e) => void submit(e)}>
      <label htmlFor="access-code">{t("gate.accessCodeLabel")}</label>
      <div className={css.stack}>
        <input id="access-code" className={css.code} autoComplete="off" autoCapitalize="characters"
               spellCheck={false} value={code} placeholder="XXXX-XXXX"
               onChange={(e) => setCode(formatAccessCode(e.target.value))} />
        <button className={css.primary} type="submit" disabled={busy || !ready}>{t("gate.openByCode")}</button>
      </div>
      <p className={css.note}>{t("gate.codeNote")}</p>
      {error && <p className={css.error} role="alert">{error}</p>}
    </form>
  );
}
