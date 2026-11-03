"""Login by e-mail code (decision 2026-10-31, docs/database.md, "Login"): a person enters an
e-mail, gets 6 digits, enters them and is in. No passwords; the code confirms the e-mail, so a
code login is a provider account "email" with a confirmed address (access.oauth_login): the
same e-mail from Google is the same user.

A code lives CODE_MINUTES, only the last one issued is valid; at most CODE_ATTEMPTS wrong
entries, a new code no more often than CODE_RESEND_SECONDS and at most CODE_PER_HOUR per hour
per address. The database stores only the sha256 of "email:code". Functions do not commit,
like access.py.
"""

from __future__ import annotations

import hmac
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from floorplan_engine.service.db.access import AccessError, _aware, now, token_hash
from floorplan_engine.service.db.models import EmailCode

PROVIDER = "email"
CODE_MINUTES = 10
CODE_ATTEMPTS = 5
CODE_RESEND_SECONDS = 60
CODE_PER_HOUR = 5

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class TooSoonError(AccessError):
    """A code is requested too often; seconds is how long until the next one is allowed."""

    def __init__(self, message: str, seconds: int) -> None:
        super().__init__(message)
        self.seconds = seconds


def normalize_email(email: str) -> str:
    """Address without spaces, lower case; AccessError if it does not look like an e-mail."""
    email = email.strip().lower()
    if len(email) > 320 or not EMAIL_RE.match(email):
        raise AccessError("Это не похоже на адрес почты")
    return email


def _hash(email: str, code: str) -> str:
    return token_hash(f"{email}:{code}")


def issue_code(session: Session, email: str, t: datetime | None = None) -> str:
    """New code for the address (earlier ones stop working); returns the code itself, for the
    e-mail.
    """
    t = t or now()
    email = normalize_email(email)
    recent = list(
        session.scalars(
            select(EmailCode)
            .where(EmailCode.email == email, EmailCode.created_at > t - timedelta(hours=1))
            .order_by(EmailCode.created_at.desc())
        )
    )
    if recent:
        wait = CODE_RESEND_SECONDS - (t - _aware(recent[0].created_at)).total_seconds()
        if wait > 0:
            raise TooSoonError("Код уже отправлен — новый можно запросить позже", int(wait) + 1)
    if len(recent) >= CODE_PER_HOUR:
        oldest = min(_aware(r.created_at) for r in recent)
        wait = 3600 - (t - oldest).total_seconds()
        raise TooSoonError("Слишком много кодов на этот адрес — попробуйте позже", int(wait) + 1)
    for row in session.scalars(
        select(EmailCode).where(EmailCode.email == email, EmailCode.used_at.is_(None))
    ):
        row.used_at = t  # only the last code is valid
    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(
        EmailCode(
            email=email,
            code_hash=_hash(email, code),
            attempts=0,
            created_at=t,
            expires_at=t + timedelta(minutes=CODE_MINUTES),
        )
    )
    session.flush()
    return code


def check_code(session: Session, email: str, code: str, t: datetime | None = None) -> str:
    """Check a code; a correct one is used up and the address is returned. Wrong, expired or out of
    attempts gives AccessError with a message for the user."""
    t = t or now()
    email = normalize_email(email)
    code = re.sub(r"\D", "", code)
    row = session.scalar(
        select(EmailCode)
        .where(EmailCode.email == email, EmailCode.used_at.is_(None))
        .order_by(EmailCode.created_at.desc())
        .limit(1)
    )
    if row is None or _aware(row.expires_at) <= t or row.attempts >= CODE_ATTEMPTS:
        raise AccessError("Код устарел — запросите новый")
    if not hmac.compare_digest(row.code_hash, _hash(email, code)):
        row.attempts += 1
        session.flush()
        left = CODE_ATTEMPTS - row.attempts
        if left <= 0:
            raise AccessError("Неверный код, попытки кончились — запросите новый")
        raise AccessError(f"Неверный код, осталось попыток: {left}")
    row.used_at = t
    session.flush()
    return email
