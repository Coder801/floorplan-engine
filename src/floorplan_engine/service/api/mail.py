"""Login e-mails: a code by e-mail (db/email_codes.py). SMTP from the standard library, any
sending service works (Resend, Postmark, SES, Gmail); without SMTP_HOST in local development
(page address is http) the code goes to the server log, in production (https) code login is off.

Environment:
  SMTP_HOST, SMTP_PORT (587 for STARTTLS, 465 for SSL), SMTP_USER, SMTP_PASSWORD
  MAIL_FROM                    sender: "Shtroba <login@…>"
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

# Subject and body by page language
TEXTS: dict[str, tuple[str, str]] = {
    "ru": (
        "Код входа в Shtroba: {code}",
        "Ваш код входа: {code}\n\nКод действует {minutes} минут. Если вы не входили в "
        "Shtroba, просто удалите это письмо.",
    ),
    "uk": (
        "Код входу до Shtroba: {code}",
        "Ваш код входу: {code}\n\nКод дійсний {minutes} хвилин. Якщо ви не входили до "
        "Shtroba, просто видаліть цей лист.",
    ),
    "en": (
        "Your Shtroba sign-in code: {code}",
        "Your sign-in code: {code}\n\nThe code is valid for {minutes} minutes. If you did not "
        "try to sign in to Shtroba, just delete this email.",
    ),
}


class MailError(RuntimeError):
    """The e-mail was not sent."""


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
    """Local development without SMTP: the e-mail goes to the server log (the code shows in the
    terminal).
    """

    def send(self, to: str, subject: str, text: str) -> None:
        print(f"\n[почта → {to}] {subject}\n", flush=True)


def mailer_from_env(env: dict[str, str], local: bool) -> Mailer | None:
    """SMTP from the environment; without SMTP_HOST, the log in local development (local), otherwise
    None (code login is off)."""
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
