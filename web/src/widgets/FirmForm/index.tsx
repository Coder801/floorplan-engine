// Регистрация фирмы при первом входе (service/api/auth.py, /api/auth/firm): название, чем
// занимается (вид — studio.business), город и телефон по желанию. Фирма — одна на человека.

import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { FIRM_KINDS, registerFirm, type FirmKind } from "@/shared/auth";
import { cx } from "@/shared/cx";
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
      <label className={css.field}>
        <span>{t("firm.name")}</span>
        <input required maxLength={200} autoComplete="organization" autoFocus value={name}
               placeholder={t("firm.namePlaceholder")} onChange={(e) => setName(e.target.value)} />
      </label>
      <fieldset className={css.kinds}>
        <legend>{t("firm.kind")}</legend>
        {FIRM_KINDS.map((k) => (
          <label key={k} className={cx(css.kind, kind === k && css.on)}>
            <input type="radio" name="business" value={k} checked={kind === k} onChange={() => setKind(k)} />
            <b>{t(`firm.kinds.${k}`)}</b>
            <span className="small muted">{t(`firm.kinds.${k}Note`)}</span>
          </label>
        ))}
      </fieldset>
      <div className={css.pair}>
        <label className={css.field}>
          <span>{t("firm.city")} <i className="muted">{t("firm.optional")}</i></span>
          <input maxLength={100} autoComplete="address-level2" value={city} onChange={(e) => setCity(e.target.value)} />
        </label>
        <label className={css.field}>
          <span>{t("firm.phone")} <i className="muted">{t("firm.optional")}</i></span>
          <input type="tel" maxLength={40} autoComplete="tel" value={phone} placeholder="+380…"
                 onChange={(e) => setPhone(e.target.value)} />
        </label>
      </div>
      {error && <p className={css.error} role="alert">{error}</p>}
      <div className={css.actions}>
        <button type="button" disabled={busy} onClick={onBack}>{t("firm.back")}</button>
        <button type="submit" className={css.primary} disabled={busy || !name.trim()}>{t("firm.submit")}</button>
      </div>
    </form>
  );
}
