"""Вход по телефону через бота Telegram: билеты (db/telegram_login.py), разбор обновлений
бота с подделкой Bot API (api/telegram.py), маршруты, вход, суперпользователь и владелец
папок по номеру (api/auth.py)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from floorplan_engine.service.api import telegram
from floorplan_engine.service.api.auth import COOKIE, Auth, AuthConfig, identity
from floorplan_engine.service.api.viewer import create_viewer
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import telegram_login as tg
from floorplan_engine.service.db.session import make_sessions
from tests.service.test_auth import SECRET, _folder


class FakeBot:
    """Bot API без сети: помнит отправленное и вебхук."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str, str | None]] = []
        self.webhook: tuple[str, str] | None = None

    def get_me(self) -> str:
        return "ShtrobaBot"

    def send_message(self, chat_id: int, body: str, contact_button: str | None = None) -> None:
        self.sent.append((chat_id, body, contact_button))

    def get_updates(self, offset: int, timeout: int) -> list[dict[str, Any]]:
        return []

    def set_webhook(self, url: str, secret: str) -> None:
        self.webhook = (url, secret)


def start_update(chat: int, user: int, token: str, name: str = "Ann") -> dict[str, Any]:
    sender = {"id": user, "first_name": name, "language_code": "uk"}
    return {
        "update_id": 1,
        "message": {"chat": {"id": chat}, "from": sender, "text": f"/start {token}"},
    }


def contact_update(chat: int, user: int, phone: str, owner: int | None = None) -> dict[str, Any]:
    contact = {"phone_number": phone, "user_id": owner or user}
    sender = {"id": user, "language_code": "uk"}
    return {"update_id": 2, "message": {"chat": {"id": chat}, "from": sender, "contact": contact}}


def test_normalize_phone_and_identity() -> None:
    assert tg.normalize_phone("+38 (050) 123-45-67") == "+380501234567"
    assert tg.normalize_phone("380501234567") == "+380501234567"
    with pytest.raises(acc.AccessError):
        tg.normalize_phone("12345")
    assert identity(" Ann@Example.com ") == "ann@example.com"
    assert identity("+38 050 123 45 67") == "+380501234567"
    assert tg.is_phone("+380501234567") and not tg.is_phone("a@b.c")


def test_ticket_lifecycle(db: Session) -> None:
    token = tg.issue_ticket(db, "uk")
    assert tg.claim_ticket(db, token) is None  # номера ещё нет — ждём
    assert tg.bind_chat(db, "нет-такого", 1, "u1") is None
    ticket = tg.bind_chat(db, token, 1, "u1", "Ann")
    assert ticket is not None and ticket.lang == "uk" and ticket.name == "Ann"
    assert tg.bind_chat(db, token, 2, "u2") is None  # билет уже за другим чатом
    assert tg.confirm_phone(db, 1, "u2", "380501234567") is None  # не тот пользователь
    confirmed = tg.confirm_phone(db, 1, "u1", "380501234567")
    assert confirmed is not None and confirmed.phone == "+380501234567"
    claimed = tg.claim_ticket(db, token)
    assert claimed is not None and claimed.phone == "+380501234567"
    with pytest.raises(acc.AccessError):  # одноразовый
        tg.claim_ticket(db, token)
    old = tg.issue_ticket(db, "ru", t=acc.now() - timedelta(minutes=tg.TICKET_MINUTES + 1))
    with pytest.raises(acc.AccessError):
        tg.claim_ticket(db, old)


def test_handle_update_replies(db: Session) -> None:
    bot = FakeBot()
    token = tg.issue_ticket(db, "uk")
    telegram.handle_update(db, bot, start_update(7, 42, token))
    assert bot.sent[-1][0] == 7 and bot.sent[-1][2] == "Поділитися номером"
    telegram.handle_update(db, bot, contact_update(7, 42, "+380501112233", owner=99))
    assert "власний" in bot.sent[-1][1] and bot.sent[-1][2] is not None  # чужой контакт
    telegram.handle_update(db, bot, contact_update(7, 42, "+380501112233"))
    assert bot.sent[-1][1].startswith("Готово") and bot.sent[-1][2] is None
    telegram.handle_update(db, bot, start_update(8, 43, "мусор"))
    assert "застаріло" in bot.sent[-1][1]
    plain = {"update_id": 3, "message": {"chat": {"id": 9}, "from": {"id": 44}, "text": "привет"}}
    telegram.handle_update(db, bot, plain)
    assert "только для входа" in bot.sent[-1][1]
    before = len(bot.sent)
    telegram.handle_update(db, bot, {"update_id": 4, "edited_message": {}})  # не сообщение
    assert len(bot.sent) == before


def test_same_phone_is_same_user_and_superuser(db: Session) -> None:
    a = acc.oauth_login(db, "telegram", "42", None, False, "Ann", phone="+380501112233")
    b = acc.oauth_login(
        db, "sms", "x", None, False, phone="+380501112233", superusers=("+380501112233",)
    )
    assert a.id == b.id and b.is_superuser and b.phone == "+380501112233"


def test_telegram_routes_login_superuser_and_owner(pg: Engine, tmp_path: Path) -> None:
    engine = pg
    root = tmp_path / "projects"
    _folder(root, "kv1")
    bot = FakeBot()
    config = AuthConfig(SECRET, "http://t", superusers=("+380501112233",), owner="+380501112233")
    auth = Auth(config, make_sessions(engine), telegram=bot)
    client = TestClient(create_viewer(root, auth))
    assert client.get("/api/auth/me").json()["telegram"] is True

    r = client.post("/api/auth/telegram/start", json={"lang": "uk"})
    token = r.json()["token"]
    assert r.json()["url"] == f"https://t.me/ShtrobaBot?start={token}"
    assert client.get("/api/auth/telegram/status", params={"token": token}).json() == {
        "status": "pending"
    }
    assert client.get("/api/auth/telegram/status", params={"token": "x"}).status_code == 410

    with auth.db() as db:
        telegram.handle_update(db, bot, start_update(7, 42, token, "Ann"))
        telegram.handle_update(db, bot, contact_update(7, 42, "380501112233"))
    done = client.get("/api/auth/telegram/status", params={"token": token})
    assert done.json()["status"] == "done" and COOKIE in done.cookies
    me = client.get("/api/auth/me").json()["user"]
    assert me["phone"] == "+380501112233" and me["superuser"] and me["name"] == "Ann"
    assert client.get("/api/auth/telegram/status", params={"token": token}).status_code == 410

    # Вебхук: без секрета — 403, с секретом — обновление разобрано
    assert client.post("/api/auth/telegram/webhook", json={}).status_code == 403
    hello = {"update_id": 5, "message": {"chat": {"id": 1}, "from": {"id": 2}, "text": "hi"}}
    ok = client.post(
        "/api/auth/telegram/webhook",
        json=hello,
        headers={"X-Telegram-Bot-Api-Secret-Token": auth.webhook_secret()},
    )
    assert ok.status_code == 200 and bot.sent[-1][0] == 1

    # Владелец папок по телефону: выбрал «Фирма» — папки в его студии
    r = client.post("/api/auth/firm", json={"name": "Штроба", "business": "electric"})
    assert r.status_code == 200
    assert {p["name"] for p in client.get("/api/projects").json()} == {"kv1"}

    # На https при старте ставится вебхук с секретом
    secure = Auth(AuthConfig(SECRET, "https://t"), make_sessions(engine), telegram=bot)
    secure.start_telegram()
    assert bot.webhook == ("https://t/api/auth/telegram/webhook", secure.webhook_secret())

    off = TestClient(create_viewer(root, Auth(config, make_sessions(engine))))
    assert off.get("/api/auth/me").json()["telegram"] is False
    assert off.post("/api/auth/telegram/start", json={}).status_code == 503
