"""Бот Telegram для входа по номеру телефона (правила на базе — db/telegram_login.py).

Bot API ходит сюда двумя путями: на https — вебхук /api/auth/telegram/webhook (ставится при
старте, секрет — в заголовке); локально на http Telegram до сервера не достучится, поэтому
сервер сам опрашивает getUpdates в фоновом потоке. Разбор обновлений общий — handle_update.
Сеть — только здесь (httpx), как и положено service/.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from sqlalchemy.orm import Session

from floorplan_engine.service.db import telegram_login as tg
from floorplan_engine.service.db.access import AccessError

log = logging.getLogger(__name__)
API = "https://api.telegram.org"
POLL_TIMEOUT = 25  # секунд long polling
POLL_RETRY = 5  # секунд до повтора после ошибки сети

TEXTS: dict[str, dict[str, str]] = {
    "share": {
        "ru": "Нажмите кнопку ниже, чтобы поделиться номером телефона — так мы узнаем вас "
        "без пароля.",
        "uk": "Натисніть кнопку нижче, щоб поділитися номером телефону — так ми впізнаємо вас "
        "без пароля.",
        "en": "Tap the button below to share your phone number — that is how we sign you in "
        "without a password.",
    },
    "button": {"ru": "Поделиться номером", "uk": "Поділитися номером", "en": "Share phone number"},
    "done": {
        "ru": "Готово — вернитесь на страницу Штробы, вход уже выполнен.",
        "uk": "Готово — поверніться на сторінку Штроби, вхід уже виконано.",
        "en": "Done — go back to the Shtroba page, you are signed in.",
    },
    "stale": {
        "ru": "Ссылка устарела. Откройте страницу входа и нажмите «Войти через Telegram» ещё раз.",
        "uk": "Посилання застаріло. Відкрийте сторінку входу й натисніть «Увійти через Telegram» "
        "ще раз.",
        "en": "This link has expired. Open the sign-in page and tap “Sign in with Telegram” again.",
    },
    "not_yours": {
        "ru": "Нужен ваш собственный номер: нажмите кнопку «Поделиться номером».",
        "uk": "Потрібен ваш власний номер: натисніть кнопку «Поділитися номером».",
        "en": "Please share your own number using the button.",
    },
    "hint": {
        "ru": "Этот бот только для входа на сайт Штробы: откройте страницу входа и нажмите "
        "«Войти через Telegram».",
        "uk": "Цей бот лише для входу на сайт Штроби: відкрийте сторінку входу й натисніть "
        "«Увійти через Telegram».",
        "en": "This bot only signs you in to Shtroba: open the sign-in page and tap "
        "“Sign in with Telegram”.",
    },
}


def text(key: str, lang: str) -> str:
    return TEXTS[key].get(lang, TEXTS[key]["ru"])


class TelegramApi(Protocol):
    """Что нужно от Bot API; в тестах — подделка."""

    def get_me(self) -> str:
        """Имя бота (username) для ссылки t.me/<имя>."""
        ...

    def send_message(self, chat_id: int, body: str, contact_button: str | None = None) -> None:
        """Сообщение; contact_button — подпись кнопки «поделиться номером» (иначе клавиатура
        убирается)."""
        ...

    def get_updates(self, offset: int, timeout: int) -> list[dict[str, Any]]: ...

    def set_webhook(self, url: str, secret: str) -> None:
        """Пустой url — вебхук снимается (перед getUpdates)."""
        ...


@dataclass
class TelegramBot:
    """Bot API по HTTPS (TELEGRAM_BOT_TOKEN)."""

    token: str
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=POLL_TIMEOUT + 10))

    def _call(self, method: str, **params: Any) -> Any:
        r = self.client.post(f"{API}/bot{self.token}/{method}", json=params)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {data.get('description', r.status_code)}")
        return data["result"]

    def get_me(self) -> str:
        return str(self._call("getMe")["username"])

    def send_message(self, chat_id: int, body: str, contact_button: str | None = None) -> None:
        markup: dict[str, Any] = (
            {
                "keyboard": [[{"text": contact_button, "request_contact": True}]],
                "one_time_keyboard": True,
                "resize_keyboard": True,
            }
            if contact_button
            else {"remove_keyboard": True}
        )
        self._call("sendMessage", chat_id=chat_id, text=body, reply_markup=markup)

    def get_updates(self, offset: int, timeout: int) -> list[dict[str, Any]]:
        result = self._call(
            "getUpdates", offset=offset, timeout=timeout, allowed_updates=["message"]
        )
        return list(result)

    def set_webhook(self, url: str, secret: str) -> None:
        if url:
            self._call("setWebhook", url=url, secret_token=secret, allowed_updates=["message"])
        else:
            self._call("deleteWebhook")


def telegram_from_env(env: dict[str, str]) -> TelegramBot | None:
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    return TelegramBot(token) if token else None


def handle_update(db: Session, api: TelegramApi, update: dict[str, Any]) -> None:
    """Одно обновление Bot API: «/start токен» — привязать чат к билету и попросить номер;
    контакт — подтвердить номер; остальное — подсказка. Ошибки — ответом пользователю."""
    msg = update.get("message")
    if not isinstance(msg, dict):
        return
    chat_id = int(msg["chat"]["id"])
    sender = msg.get("from") or {}
    user_id = str(sender.get("id", ""))
    lang = str(sender.get("language_code") or "ru")[:2]
    name = " ".join(s for s in (sender.get("first_name"), sender.get("last_name")) if s)
    contact = msg.get("contact")
    if isinstance(contact, dict):
        if str(contact.get("user_id", "")) != user_id:
            api.send_message(chat_id, text("not_yours", lang), text("button", lang))
            return
        try:
            ticket = tg.confirm_phone(db, chat_id, user_id, str(contact.get("phone_number", "")))
        except AccessError:
            ticket = None
        if ticket is None:
            api.send_message(chat_id, text("stale", lang))
            return
        if not ticket.name:
            ticket.name = name[:200]
        api.send_message(chat_id, text("done", ticket.lang))
        return
    body = str(msg.get("text") or "")
    if body.startswith("/start"):
        token = body.partition(" ")[2].strip()
        ticket = tg.bind_chat(db, token, chat_id, user_id, name) if token else None
        if ticket is None:
            api.send_message(chat_id, text("stale", lang))
            return
        api.send_message(chat_id, text("share", ticket.lang), text("button", ticket.lang))
        return
    api.send_message(chat_id, text("hint", lang))


def start_polling(api: TelegramApi, handle: Callable[[dict[str, Any]], None]) -> threading.Thread:
    """Локально (http): вебхук снять и опрашивать getUpdates в фоне до конца процесса."""

    def loop() -> None:
        offset = 0
        try:
            api.set_webhook("", "")
        except Exception as exc:  # сеть: пишем и пробуем опрос
            log.warning("Telegram deleteWebhook: %s", exc)
        while True:
            try:
                for update in api.get_updates(offset, POLL_TIMEOUT):
                    offset = int(update.get("update_id", offset)) + 1
                    try:
                        handle(update)
                    except Exception:  # одно обновление не должно ронять опрос
                        log.exception("Telegram: обновление не разобрано")
            except Exception as exc:  # сеть: подождать и снова
                log.warning("Telegram getUpdates: %s", exc)
                time.sleep(POLL_RETRY)

    thread = threading.Thread(target=loop, name="telegram-poll", daemon=True)
    thread.start()
    return thread
