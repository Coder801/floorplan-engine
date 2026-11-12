// Login by project access code (service/api/auth.py, /api/auth/code): the studio gave a
// "XXXX-XXXX" code, the person enters it and views that one project without an account. An
// error (wrong code, expired, too many attempts) shows under the field, text from the server.

import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { loginByCode } from "@/shared/auth";
import { Button } from "@/ui/Button";
import { Text } from "@/ui/Text";
import { TextField } from "@/ui/TextField";
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
      <TextField id="access-code" label={t("gate.accessCodeLabel")} size="lg" mono inputClassName={css.code}
                 autoComplete="off" autoCapitalize="characters" spellCheck={false} value={code} placeholder="XXXX-XXXX"
                 onChange={(e) => setCode(formatAccessCode(e.target.value))} />
      <Button type="submit" variant="primary" size="lg" block disabled={busy || !ready}>{t("gate.openByCode")}</Button>
      <Text size="small" tone="muted">{t("gate.codeNote")}</Text>
      {error && <Text tone="critical" role="alert">{error}</Text>}
    </form>
  );
}
