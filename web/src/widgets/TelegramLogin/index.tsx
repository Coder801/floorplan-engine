// Telegram login (service/api/auth.py, /api/auth/telegram/*): the page gets a ticket and opens
// the bot via t.me/<bot>?start=<token>; the person taps Start and "Share number", the page polls
// the ticket and logs in. No passwords or codes; an invite from the address goes along with the poll.

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { startTelegramLogin, telegramLoginStatus, type TelegramTicket } from "@/shared/auth";
import { Button } from "@/ui/Button";
import { Text } from "@/ui/Text";
import css from "./TelegramLogin.module.scss";

const POLL_MS = 2000;

export function TelegramLogin({ onDone, invite }: { onDone: () => void; invite?: string | null }) {
  const { t, i18n } = useTranslation();
  const [ticket, setTicket] = useState<TelegramTicket | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setBusy(true); setError(null);
    try {
      const r = await startTelegramLogin(i18n.language);
      setTicket(r);
      window.open(r.url, "_blank", "noopener");  // Telegram app or the web version
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // Poll the ticket while the person is in the bot; if it expires, back to the button with an explanation
  useEffect(() => {
    if (!ticket) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const r = await telegramLoginStatus(ticket.token, invite);
        if (stopped) return;
        if (r.status === "done") { onDone(); return; }
        timer = setTimeout(tick, POLL_MS);
      } catch {
        if (stopped) return;
        setTicket(null); setError(t("gate.telegramExpired"));
      }
    };
    timer = setTimeout(tick, POLL_MS);
    return () => { stopped = true; if (timer) clearTimeout(timer); };
  }, [ticket, invite, onDone, t]);

  if (!ticket) {
    return (
      <div className={css.box}>
        <button type="button" className={css.button} disabled={busy} onClick={() => void start()}>
          <svg className={css.icon} viewBox="0 0 24 24" aria-hidden="true">
            <path d="M21.9 4.6 18.8 19.4c-.2 1-.9 1.3-1.7.8l-4.8-3.5-2.3 2.2c-.3.3-.5.5-1 .5l.3-4.8 8.8-8c.4-.3-.1-.5-.6-.2L6.7 13.3 2 11.8c-1-.3-1-1 .2-1.5L20.6 3.3c.9-.3 1.6.2 1.3 1.3Z" />
          </svg>
          {t("gate.telegram")}
        </button>
        {error && <Text size="small" tone="critical" role="alert">{error}</Text>}
      </div>
    );
  }
  return (
    <div className={css.box}>
      <p className={css.waiting} role="status">
        <span className={css.spinner} aria-hidden="true" />
        {t("gate.telegramWaiting")}
      </p>
      <div className={css.links}>
        <Button variant="link" className={css.link} href={ticket.url} target="_blank" rel="noopener noreferrer">{t("gate.telegramOpen")}</Button>
        <Button variant="link" className={css.link} onClick={() => setTicket(null)}>{t("gate.telegramCancel")}</Button>
      </div>
    </div>
  );
}
