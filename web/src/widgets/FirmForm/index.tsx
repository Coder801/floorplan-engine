// Firm registration on first login (service/api/auth.py, /api/auth/firm): name, what it does
// (the kind, studio.business), city and phone optionally. One firm per person.

import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { FIRM_KINDS, registerFirm, type FirmKind } from "@/shared/auth";
import { Button } from "@/ui/Button";
import { RadioCard } from "@/ui/RadioCard";
import { Text } from "@/ui/Text";
import { TextField } from "@/ui/TextField";
import css from "./FirmForm.module.scss";

export function FirmForm({ onBack, onDone }: { onBack: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<FirmKind | null>(null);
  const [city, setCity] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!kind) { setError(t("firm.chooseKind")); return; }
    setBusy(true); setError(null);
    try {
      await registerFirm({ name, business: kind, city, phone });
      onDone();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <form className={css.form} onSubmit={(e) => void submit(e)}>
      <TextField label={t("firm.name")} size="lg" required maxLength={200} autoComplete="organization" autoFocus value={name}
                 placeholder={t("firm.namePlaceholder")} onChange={(e) => setName(e.target.value)} />
      <fieldset className={css.kinds}>
        <legend>{t("firm.kind")}</legend>
        {FIRM_KINDS.map((k) => (
          <RadioCard key={k} name="business" value={k} checked={kind === k} onChange={() => setKind(k)}
                     title={t(`firm.kinds.${k}`)} description={t(`firm.kinds.${k}Note`)} />
        ))}
      </fieldset>
      <div className={css.pair}>
        <TextField label={<>{t("firm.city")} {t("firm.optional")}</>} size="lg" maxLength={100} autoComplete="address-level2"
                   value={city} onChange={(e) => setCity(e.target.value)} />
        <TextField label={<>{t("firm.phone")} {t("firm.optional")}</>} size="lg" type="tel" maxLength={40} autoComplete="tel"
                   value={phone} placeholder="+380…" onChange={(e) => setPhone(e.target.value)} />
      </div>
      {error && <Text tone="critical" role="alert">{error}</Text>}
      <div className={css.actions}>
        <Button size="lg" disabled={busy} onClick={onBack}>{t("firm.back")}</Button>
        <Button type="submit" variant="primary" size="lg" disabled={busy || !name.trim()}>{t("firm.submit")}</Button>
      </div>
    </form>
  );
}
