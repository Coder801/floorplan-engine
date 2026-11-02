"""Вход по номеру телефона через бота Telegram (решение 2026-11-01, docs/database.md,
«Вход»): страница просит билет и открывает ссылку t.me/<бот>?start=<токен>; человек жмёт
Start и кнопку «Поделиться номером»; бот получает его контакт (номер подтверждён самим
Telegram), ставит номер в билет; страница опрашивает билет — и вошла. Паролей и кодов нет.

Учётка — провайдер «telegram» (access.oauth_login) с номером: тот же номер в другой учётке —
тот же пользователь. Билет живёт TICKET_MINUTES, одноразовый; в базе — только sha256 токена.
Здесь — правила на базе, без сети; разговор с Bot API — service/api/telegram.py.
Функции не делают commit, как access.py.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from floorplan_engine.service.db.access import AccessError, _aware, new_token, now, token_hash
from floorplan_engine.service.db.models import LoginTicket

PROVIDER = "telegram"
TICKET_MINUTES = 10


def normalize_phone(raw: str) -> str:
    """Номер в виде «+380501234567»: только цифры, от 8 до 15 (E.164); иначе AccessError.
    Так же записаны телефоны в SHTROBA_SUPERUSERS и SHTROBA_OWNER."""
    digits = re.sub(r"\D", "", raw)
    if not 8 <= len(digits) <= 15:
        raise AccessError("Это не похоже на номер телефона")
    return f"+{digits}"


def is_phone(value: str) -> bool:
    """Строка из окружения — телефон (иначе email)."""
    return "@" not in value and bool(re.fullmatch(r"\+?[\d\s()-]{8,20}", value.strip()))


def issue_ticket(session: Session, lang: str = "ru", t: datetime | None = None) -> str:
    """Новый билет входа; вернёт токен для ссылки на бота."""
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
    if ticket is None or ticket.used_at is not None or _aware(ticket.expires_at) <= t:
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
    """«/start токен» в боте: билет запоминает чат. Билета нет, он устарел, использован или
    уже занят другим чатом — None (бот отвечает «откройте ссылку заново»)."""
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
    """Контакт в боте: номер — в последний живой билет этого чата. Контакт не свой, билета
    нет или устарел — None."""
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
    """Опрос страницы: номер уже есть — билет гасится и возвращается (дальше вход);
    ещё нет — None; билета нет или устарел — AccessError."""
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
