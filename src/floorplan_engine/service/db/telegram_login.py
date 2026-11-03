"""Login by phone number through a Telegram bot (decision 2026-11-01, docs/database.md,
"Login"): the page asks for a ticket and opens the link t.me/<bot>?start=<token>; the person
taps Start and the "Share number" button; the bot receives their contact (the number is
confirmed by Telegram itself) and puts the number into the ticket; the page polls the ticket
and is logged in. No passwords and no codes.

The account is provider "telegram" (access.oauth_login) with the number: the same number in
another account is the same user. A ticket lives TICKET_MINUTES and is one-time; only the
sha256 of the token is stored. This module holds the database rules, no network; talking to
the Bot API is in service/api/telegram.py. Functions do not commit, like access.py.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from floorplan_engine.service.db.access import AccessError, aware, new_token, now, token_hash
from floorplan_engine.service.db.models import LoginTicket

PROVIDER = "telegram"
TICKET_MINUTES = 10


def normalize_phone(raw: str) -> str:
    """Number in the form "+380501234567": digits only, 8 to 15 of them (E.164); otherwise
    AccessError.
    Phones in SHTROBA_SUPERUSERS and SHTROBA_OWNER are written the same way."""
    digits = re.sub(r"\D", "", raw)
    if not 8 <= len(digits) <= 15:
        raise AccessError("Это не похоже на номер телефона")
    return f"+{digits}"


def is_phone(value: str) -> bool:
    """An environment string is a phone (otherwise an e-mail)."""
    return "@" not in value and bool(re.fullmatch(r"\+?[\d\s()-]{8,20}", value.strip()))


def issue_ticket(session: Session, lang: str = "ru", t: datetime | None = None) -> str:
    """New login ticket; returns the token for the bot link."""
    t = t or now()
    token = new_token()
    session.add(
        LoginTicket(
            token_hash=token_hash(token),
            lang=lang if lang in ("ru", "uk", "en") else "ru",
            created_at=t,
            expires_at=t + timedelta(minutes=TICKET_MINUTES),
        )
    )
    session.flush()
    return token


def _alive(ticket: LoginTicket | None, t: datetime) -> LoginTicket | None:
    if ticket is None or ticket.used_at is not None or aware(ticket.expires_at) <= t:
        return None
    return ticket


def bind_chat(
    session: Session,
    token: str,
    chat_id: int,
    telegram_user_id: str,
    name: str = "",
    t: datetime | None = None,
) -> LoginTicket | None:
    """Handle "/start token" in the bot: the ticket remembers the chat. A missing, expired, used
    ticket or one already taken by another chat gives None (the bot replies "open the link
    again")."""
    t = t or now()
    ticket = _alive(
        session.scalar(select(LoginTicket).where(LoginTicket.token_hash == token_hash(token))), t
    )
    if ticket is None or (ticket.chat_id is not None and ticket.chat_id != chat_id):
        return None
    ticket.chat_id = chat_id
    ticket.telegram_user_id = telegram_user_id
    ticket.name = name[:200]
    session.flush()
    return ticket


def confirm_phone(
    session: Session, chat_id: int, telegram_user_id: str, phone: str, t: datetime | None = None
) -> LoginTicket | None:
    """Contact in the bot: the number goes into the latest live ticket of this chat. Someone else's
    contact or a missing or expired ticket gives None."""
    t = t or now()
    ticket = _alive(
        session.scalar(
            select(LoginTicket)
            .where(LoginTicket.chat_id == chat_id, LoginTicket.phone.is_(None))
            .order_by(LoginTicket.created_at.desc())
            .limit(1)
        ),
        t,
    )
    if ticket is None or ticket.telegram_user_id != telegram_user_id:
        return None
    ticket.phone = normalize_phone(phone)
    session.flush()
    return ticket


def claim_ticket(session: Session, token: str, t: datetime | None = None) -> LoginTicket | None:
    """Page poll: if the number is there, the ticket is used up and returned (login follows);
    not yet gives None; a missing or expired ticket gives AccessError."""
    t = t or now()
    ticket = session.scalar(select(LoginTicket).where(LoginTicket.token_hash == token_hash(token)))
    if _alive(ticket, t) is None:
        raise AccessError("Ссылка устарела — начните вход заново")
    assert ticket is not None
    if ticket.phone is None:
        return None
    ticket.used_at = t
    session.flush()
    return ticket
