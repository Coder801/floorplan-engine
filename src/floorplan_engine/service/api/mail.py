"""Письма входа: код на почту (db/email_codes.py). SMTP — из стандартной библиотеки, подходит
любой сервис отправки (Resend, Postmark, SES, Gmail); без SMTP_HOST на локальной разработке
(адрес страницы — http) код пишется в лог сервера, в работе (https) вход по коду выключен.

Окружение:
  SMTP_HOST, SMTP_PORT (587 — STARTTLS, 465 — SSL), SMTP_USER, SMTP_PASSWORD
  MAIL_FROM                    отправитель: «Штроба <login@…>»
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from floorplan_engine.service.db.email_codes import CODE_MINUTES

log = logging.getLogger("floorplan_engine.mail")

# Тема и текст письма по языку страницы
TEXTS: dict[str, tuple[str, str]] = {
    "ru": (
        "Код входа в Штробу: {code}",
        "Ваш код входа: {code}\n\nКод действует {minutes} минут. Если вы не входили в "
        "Штробу, просто удалите это письмо.",
    ),
    "uk": (
        "Код входу до Штроби: {code}",
        "Ваш код входу: {code}\n\nКод дійсний {minutes} хвилин. Якщо ви не входили до "
        "Штроби, просто видаліть цей лист.",
    ),
    "en": (
        "Your Shtroba sign-in code: {code}",
        "Your sign-in code: {code}\n\nThe code is valid for {minutes} minutes. If you did not "
        "try to sign in to Shtroba, just delete this email.",
    ),
}


class MailError(RuntimeError):
    """Письмо не ушло."""


class Mailer(Protocol):
    def send(self, to: str, subject: str, text: str) -> None: ...


@dataclass(frozen=True)
class SmtpMailer:
    host: str
    port: int
    user: str
    password: str
    sender: str

    def send(self, to: str, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, to, subject
        msg.set_content(text)
        context = ssl.create_default_context()
        try:
            if self.port == 465:
                with smtplib.SMTP_SSL(self.host, self.port, context=context, timeout=15) as s:
                    self._deliver(s, msg)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=15) as s:
                    s.starttls(context=context)
                    self._deliver(s, msg)
        except (smtplib.SMTPException, OSError) as exc:
            log.warning("письмо на %s не ушло: %s", to, exc)
            raise MailError("письмо не ушло") from exc

    def _deliver(self, s: smtplib.SMTP, msg: EmailMessage) -> None:
        if self.user:
            s.login(self.user, self.password)
        s.send_message(msg)


class LogMailer:
    """Локальная разработка без SMTP: письмо — в лог сервера (код виден в терминале)."""

    def send(self, to: str, subject: str, text: str) -> None:
        print(f"\n[почта → {to}] {subject}\n", flush=True)


def mailer_from_env(env: dict[str, str], local: bool) -> Mailer | None:
    """SMTP по окружению; без SMTP_HOST — лог на локальной разработке (local), иначе None
    (вход по коду выключен)."""
    host = env.get("SMTP_HOST", "").strip()
    if not host:
        return LogMailer() if local else None
    return SmtpMailer(
        host=host,
        port=int(env.get("SMTP_PORT") or 587),
        user=env.get("SMTP_USER", ""),
        password=env.get("SMTP_PASSWORD", ""),
        sender=env.get("MAIL_FROM") or env.get("SMTP_USER", ""),
    )


def send_code(mailer: Mailer, to: str, code: str, lang: str) -> None:
    subject, body = TEXTS.get(lang, TEXTS["ru"])
    mailer.send(to, subject.format(code=code), body.format(code=code, minutes=CODE_MINUTES))
