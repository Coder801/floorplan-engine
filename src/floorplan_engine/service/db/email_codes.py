"""Вход по коду на почту (решение 2026-10-31, docs/database.md, «Вход»): человек вводит email,
получает 6 цифр, вводит — и вошёл. Паролей нет; код подтверждает почту, поэтому вход по коду —
учётка провайдера «email» с подтверждённым адресом (access.oauth_login): тот же email из
Google — тот же пользователь.

Код живёт CODE_MINUTES, действует последний выданный; неверных вводов — не больше
CODE_ATTEMPTS, новый код — не чаще CODE_RESEND_SECONDS и не больше CODE_PER_HOUR в час на
адрес. В базе — только sha256 «email:код». Функции не делают commit, как access.py.
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
    """Код просят слишком часто; seconds — через сколько можно снова."""

    def __init__(self, message: str, seconds: int) -> None:
        super().__init__(message)
        self.seconds = seconds


def normalize_email(email: str) -> str:
    """Адрес без пробелов, в нижнем регистре; не похож на email — AccessError."""
    email = email.strip().lower()
    if len(email) > 320 or not EMAIL_RE.match(email):
        raise AccessError("Это не похоже на адрес почты")
    return email


def _hash(email: str, code: str) -> str:
    return token_hash(f"{email}:{code}")


def issue_code(session: Session, email: str, t: datetime | None = None) -> str:
    """Новый код для адреса (прежние перестают действовать); вернёт сам код — для письма."""
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
        row.used_at = t  # действует только последний код
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
    """Проверить код; верный — код погашен, вернёт адрес. Неверный, устаревший, кончились
    попытки — AccessError с сообщением для пользователя."""
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
