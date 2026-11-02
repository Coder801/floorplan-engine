"""Вход в просмотр: Google (OAuth, Authlib) и код на почту, сессии в cookie, приглашения,
гость отладки.

Включается окружением (SHTROBA_AUTH=on); без него просмотр открыт, как раньше (локально).
Правила доступа — db/access.py; здесь — веб: маршруты /api/auth/*, /api/invites/* и
промежуточный слой, который проверяет доступ к /api/projects/{имя}/… (решения 2026-10-28,
docs/database.md, «Вход»).

Окружение:
  SHTROBA_AUTH=on              включить вход
  SHTROBA_SECRET               ключ подписи cookie состояния OAuth (длинная случайная строка)
  SHTROBA_PUBLIC_URL           адрес страницы: https://… (там же /api) или http://127.0.0.1:5173
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET   OAuth-клиент Google; нет — кнопки Google нет
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM   письма с кодом входа (mail.py);
                               без SMTP на http (локально) код — в лог сервера, на https —
                               входа по коду нет
  TELEGRAM_BOT_TOKEN           бот для входа по номеру телефона (api/telegram.py); нет — кнопки
                               «Войти через Telegram» нет. На https бот ходит вебхуком
                               <SHTROBA_PUBLIC_URL>/api/auth/telegram/webhook, на http (локально)
                               сервер сам опрашивает Bot API
  Код доступа к проекту (db/access_codes.py) настройки не требует: его выдаёт команда
  `floorplan-engine access code projects/<имя>`, вход — /api/auth/code.
  SHTROBA_SUPERUSERS           email или телефоны («+380…») владельцев платформы через запятую
  SHTROBA_OWNER                email или телефон владельца проектов из папок: при его входе и
                               выборе «Фирма» папки без строки в базе уходят в его студию
                               (access.adopt_folders)
  SHTROBA_DEV_LOGIN=1          «Зайти для разработки»: вход без Google и письма под первым
                               адресом SHTROBA_SUPERUSERS; только http (локально), не production
  SHTROBA_VISITOR=1            «Войти как гость» без входа — только для отладки: видит все
                               проекты, только чтение; в окружении Railway «production» запрещён
  DATABASE_URL                 база (db/session.py)
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from floorplan_engine.service.api import telegram
from floorplan_engine.service.api.mail import Mailer, MailError, send_code
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import access_codes
from floorplan_engine.service.db import email_codes as codes
from floorplan_engine.service.db import telegram_login as tg
from floorplan_engine.service.db.models import AppUser, Project

log = logging.getLogger(__name__)
COOKIE = "shtroba_session"
WEBHOOK_PATH = "/api/auth/telegram/webhook"
GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"
# Без входа: сам вход, приглашения (посмотреть, куда зовут), описание API
OPEN_PREFIXES = ("/api/auth/", "/api/invites/")
# Подбор кода доступа: не больше CODE_TRIES неверных кодов с одного адреса за CODE_WINDOW секунд
CODE_TRIES = 20
CODE_WINDOW = 600


class ConfigError(RuntimeError):
    """Окружение входа задано неверно — сервис не стартует."""


@dataclass(frozen=True)
class AuthConfig:
    secret: str
    public_url: str
    google_id: str | None = None
    google_secret: str | None = None
    superusers: tuple[str, ...] = ()
    visitor: bool = False
    dev_login: bool = False  # «Зайти для разработки» — под первым суперпользователем
    owner: str | None = None  # SHTROBA_OWNER: чьи папки проектов без строки в базе

    @property
    def google(self) -> bool:
        return bool(self.google_id and self.google_secret)

    @property
    def secure(self) -> bool:
        return self.public_url.startswith("https://")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AuthConfig | None:
        """Настройки из окружения; вход выключен — None."""
        env = dict(os.environ) if env is None else env
        if env.get("SHTROBA_AUTH", "").lower() not in {"on", "1", "true"}:
            return None
        secret = env.get("SHTROBA_SECRET", "")
        if len(secret) < 32:
            raise ConfigError("SHTROBA_SECRET — не короче 32 символов")
        public = env.get("SHTROBA_PUBLIC_URL", "").rstrip("/")
        if not public.startswith(("http://", "https://")):
            raise ConfigError("SHTROBA_PUBLIC_URL — адрес страницы, http(s)://…")
        visitor = env.get("SHTROBA_VISITOR", "").lower() in {"1", "on", "true"}
        if visitor and env.get("RAILWAY_ENVIRONMENT_NAME", "").lower() == "production":
            raise ConfigError(
                "SHTROBA_VISITOR в production запрещён: гость видит проекты клиентов — "
                "включайте его в отдельном окружении (staging)"
            )
        superusers = tuple(
            identity(e) for e in env.get("SHTROBA_SUPERUSERS", "").split(",") if e.strip()
        )
        dev = env.get("SHTROBA_DEV_LOGIN", "").lower() in {"1", "on", "true"}
        if dev and (
            public.startswith("https://")
            or env.get("RAILWAY_ENVIRONMENT_NAME", "").lower() == "production"
        ):
            raise ConfigError(
                "SHTROBA_DEV_LOGIN — только для локальной разработки (http): на сервере любой "
                "вошёл бы суперпользователем"
            )
        if dev and not superusers:
            raise ConfigError(
                "SHTROBA_DEV_LOGIN — нужен SHTROBA_SUPERUSERS: вход под первым адресом"
            )
        return cls(
            secret=secret,
            public_url=public,
            google_id=env.get("GOOGLE_CLIENT_ID") or None,
            google_secret=env.get("GOOGLE_CLIENT_SECRET") or None,
            superusers=superusers,
            visitor=visitor,
            dev_login=dev,
            owner=identity(env["SHTROBA_OWNER"]) if env.get("SHTROBA_OWNER", "").strip() else None,
        )


class CodeLimiter:
    """Неверные коды доступа по адресам клиента, в памяти процесса: CODE_TRIES за CODE_WINDOW
    секунд, дальше — 429. Код — 40 бит, перебор без этого и так не по силам, но лишние
    попытки нам ни к чему."""

    def __init__(self, tries: int = CODE_TRIES, window: float = CODE_WINDOW) -> None:
        self.tries, self.window = tries, window
        self._fails: dict[str, list[float]] = {}

    def blocked(self, key: str, t: float | None = None) -> bool:
        t = time.monotonic() if t is None else t
        recent = [f for f in self._fails.get(key, ()) if f > t - self.window]
        if recent:
            self._fails[key] = recent
        else:
            self._fails.pop(key, None)
        return len(recent) >= self.tries

    def fail(self, key: str, t: float | None = None) -> None:
        t = time.monotonic() if t is None else t
        self._fails.setdefault(key, []).append(t)


def client_ip(request: Request) -> str:
    """Адрес клиента: за прокси (Railway, Caddy) — первый из X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


def identity(value: str) -> str:
    """Кто это из окружения: телефон — как «+380…», email — в нижнем регистре (так они
    записаны у пользователя)."""
    value = value.strip()
    return tg.normalize_phone(value) if tg.is_phone(value) else value.lower()


def _user_json(db: Session, user: AppUser) -> dict[str, Any]:
    """Пользователь и его пространство: фирма (kind studio, вид и город) или личное."""
    space = acc.user_space(db, user)
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "account_type": user.account_type,
        "superuser": user.is_superuser,
        "space": None
        if space is None
        else {
            "kind": space.kind,
            "name": space.name,
            "business": space.business,
            "city": space.city,
        },
    }


@dataclass
class Auth:
    """Вход и доступ для одного приложения FastAPI."""

    config: AuthConfig
    sessions: sessionmaker[Session]
    oauth: OAuth = field(default_factory=OAuth)
    mailer: Mailer | None = None  # письма с кодом входа; None — входа по коду нет
    telegram: telegram.TelegramApi | None = None  # бот для входа по телефону; None — нет кнопки
    folders: Callable[[], Collection[str]] | None = None  # папки проектов (ставит create_viewer)
    limiter: CodeLimiter = field(default_factory=CodeLimiter)  # подбор кода доступа
    _bot_name: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.config.google:
            self.oauth.register(
                "google",
                client_id=self.config.google_id,
                client_secret=self.config.google_secret,
                server_metadata_url=GOOGLE_METADATA,
                client_kwargs={"scope": "openid email profile"},
            )

    @contextmanager
    def db(self) -> Iterator[Session]:
        with self.sessions() as s:
            yield s
            s.commit()

    def _adopt(self, db: Session, user: AppUser) -> None:
        """Владелец папок (SHTROBA_OWNER) вошёл или выбрал тип учётки — папки без строки в
        базе в его студию. Не владелец, нет папок или тип ещё не выбран — ничего."""
        owner = self.config.owner
        if owner and self.folders is not None and owner in (user.email, user.phone):
            acc.adopt_folders(db, owner, self.folders())

    # --- Telegram ------------------------------------------------------------------------

    def bot_name(self) -> str:
        """Имя бота для ссылки t.me/<имя> — один раз у Bot API."""
        assert self.telegram is not None
        if self._bot_name is None:
            self._bot_name = self.telegram.get_me()
        return self._bot_name

    def webhook_secret(self) -> str:
        return acc.token_hash(f"telegram:{self.config.secret}")

    def handle_update(self, update: dict[str, Any]) -> None:
        """Обновление от бота (вебхук или опрос) — в правила входа, в своей транзакции."""
        assert self.telegram is not None
        with self.db() as db:
            telegram.handle_update(db, self.telegram, update)

    def start_telegram(self) -> None:
        """При старте сервера: на https — вебхук, на http — опрос Bot API в фоне."""
        if self.telegram is None:
            return
        if self.config.secure:
            try:
                self.telegram.set_webhook(
                    self.config.public_url + WEBHOOK_PATH, self.webhook_secret()
                )
            except Exception as exc:  # сеть: вход без Telegram, остальное работает
                log.warning("Telegram setWebhook: %s", exc)
        else:
            telegram.start_polling(self.telegram, self.handle_update)

    # --- кто пришёл ------------------------------------------------------------------

    def principal(self, db: Session, request: Request) -> acc.Principal | None:
        token = request.cookies.get(COOKIE)
        if token:
            user = acc.session_user(db, token)
            if user is not None:
                return acc.Principal(user)
        code_id = request.session.get("code")
        if code_id:
            code = access_codes.active_code(db, uuid.UUID(code_id))
            if code is not None:
                return acc.Principal(None, code_project=code.project_id)
        if self.config.visitor and request.session.get("visitor"):
            return acc.VISITOR
        return None

    def _code_json(self, db: Session, who: acc.Principal | None) -> dict[str, Any] | None:
        """Вошедший по коду: проект кода (папка и название) для шапки и открытия проекта."""
        if who is None or not who.by_code:
            return None
        project = db.get(Project, who.code_project)
        if project is None:
            return None
        return {"project": project.slug, "name": project.name}

    def visible(self, request: Request, slugs: Collection[str]) -> set[str]:
        """Папки проектов, которые видит пришедший (для списка проектов)."""
        with self.db() as db:
            who = self.principal(db, request)
            return set() if who is None else acc.visible_slugs(db, who, slugs)

    def check(self, request: Request) -> Response | None:
        """Проверка запроса к API; None — пропустить. Нет входа — 401, нет доступа к
        проекту — 404 (чужие проекты не раскрываются), нет права — 403."""
        path = request.url.path
        if not path.startswith("/api/") or path.startswith(OPEN_PREFIXES):
            return None
        with self.db() as db:
            who = self.principal(db, request)
            if who is None:
                return JSONResponse({"detail": "нужен вход"}, status_code=401)
            parts = path.split("/")  # ["", "api", "projects", имя, …]
            if len(parts) < 4 or parts[2] != "projects" or not parts[3]:
                return None
            project = acc.project_by_slug(db, parts[3])
            role = acc.project_role(db, who, project)
            if not acc.can(role, "view"):
                return JSONResponse({"detail": f"проекта {parts[3]} нет"}, status_code=404)
            action: acc.Action = "view"
            if request.method == "POST" and parts[-1] == "wiring":
                action = "edit_wiring"
            elif request.method == "POST" and parts[-1] == "variant":
                action = "choose_variant"
            if not acc.can(role, action):
                return JSONResponse({"detail": "нет права на это действие"}, status_code=403)
            if role == "support" and project is not None:
                payload = {"path": path}
                acc.audit(db, "support_access", user=who.user, project=project, payload=payload)
            request.state.role = role
        return None

    # --- подключение к приложению ----------------------------------------------------

    def install(self, app: FastAPI) -> None:
        auth = self

        @app.middleware("http")
        async def guard(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            denied = await run_in_threadpool(auth.check, request)
            return denied if denied is not None else await call_next(request)

        # Снаружи guard: guard читает request.session (гость отладки, приглашение)
        app.add_middleware(
            SessionMiddleware,
            secret_key=self.config.secret,
            session_cookie="shtroba_oauth",
            same_site="lax",
            https_only=self.config.secure,
        )
        app.include_router(self.router())
        if self.telegram is not None:
            app.router.on_startup.append(self.start_telegram)

    def _set_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            COOKIE,
            token,
            max_age=acc.SESSION_DAYS * 24 * 3600,
            httponly=True,
            secure=self.config.secure,
            samesite="lax",
            path="/",
        )

    def router(self) -> APIRouter:
        r = APIRouter()
        cfg = self.config

        @r.get("/api/auth/me")
        def me(request: Request) -> dict[str, Any]:
            with self.db() as db:
                who = self.principal(db, request)
                user = who.user if who is not None else None
                return {
                    "auth": True,
                    "user": _user_json(db, user) if user is not None else None,
                    "visitor": who is not None and who.visitor,
                    "code": self._code_json(db, who),
                    "google": cfg.google,
                    "email": self.mailer is not None,
                    "telegram": self.telegram is not None,
                    "dev": cfg.dev_login,
                    "visitor_allowed": cfg.visitor,
                }

        @r.get("/api/auth/google/login")
        async def google_login(request: Request, invite: str | None = None) -> Response:
            if not cfg.google:
                raise HTTPException(503, "вход через Google не настроен (GOOGLE_CLIENT_ID)")
            if invite:
                request.session["invite"] = invite
            redirect = f"{cfg.public_url}/api/auth/google/callback"
            client = self.oauth.create_client("google")
            response: Response = await client.authorize_redirect(request, redirect)
            return response

        @r.get("/api/auth/google/callback")
        async def google_callback(request: Request) -> Response:
            client = self.oauth.create_client("google")
            try:
                token = await client.authorize_access_token(request)
            except OAuthError as exc:
                return RedirectResponse(f"{cfg.public_url}/?auth_error={quote(str(exc.error))}")
            info = token.get("userinfo") or {}
            invite = request.session.pop("invite", None)
            session_token, error = await run_in_threadpool(
                self._finish_login, info, invite, request.headers.get("user-agent", "")
            )
            target = f"{cfg.public_url}/" + (f"?auth_error={quote(error)}" if error else "")
            response = RedirectResponse(target)
            self._set_cookie(response, session_token)
            return response

        @r.post("/api/auth/email/start")
        def email_start(
            email: str = Body(..., embed=True), lang: str = Body("ru", embed=True)
        ) -> dict[str, Any]:
            """Код на почту. Есть ли такой пользователь, не говорит: учётка появится при входе."""
            if self.mailer is None:
                raise HTTPException(503, "вход по коду не настроен (SMTP_HOST)")
            with self.db() as db:
                try:
                    code = codes.issue_code(db, email)
                except codes.TooSoonError as exc:
                    raise HTTPException(
                        429, str(exc), headers={"Retry-After": str(exc.seconds)}
                    ) from exc
                except acc.AccessError as exc:
                    raise HTTPException(400, str(exc)) from exc
                to = codes.normalize_email(email)
                try:
                    send_code(self.mailer, to, code, lang)
                except MailError as exc:
                    raise HTTPException(503, "письмо не ушло — попробуйте позже") from exc
            return {"sent": True, "resend_in": codes.CODE_RESEND_SECONDS}

        @r.post("/api/auth/email/verify")
        def email_verify(
            request: Request,
            email: str = Body(..., embed=True),
            code: str = Body(..., embed=True),
            invite: str | None = Body(None, embed=True),
        ) -> Response:
            """Вход по коду: пользователь (тот же, что с Google, если email совпал), приглашение,
            сессия в cookie."""
            if self.mailer is None:
                raise HTTPException(503, "вход по коду не настроен (SMTP_HOST)")
            with self.db() as db:
                try:
                    address = codes.check_code(db, email, code)
                except acc.AccessError as exc:
                    raise HTTPException(400, str(exc)) from exc
            info = {"sub": address, "email": address, "email_verified": True, "name": ""}
            token, error = self._finish_login(
                info, invite, request.headers.get("user-agent", ""), codes.PROVIDER
            )
            response = JSONResponse({"ok": True, "invite_error": error})
            self._set_cookie(response, token)
            return response

        @r.post("/api/auth/telegram/start")
        def telegram_start(lang: str = Body("ru", embed=True)) -> dict[str, Any]:
            """Билет входа и ссылка на бота; страница открывает её и опрашивает status."""
            if self.telegram is None:
                raise HTTPException(503, "вход через Telegram не настроен (TELEGRAM_BOT_TOKEN)")
            try:
                bot = self.bot_name()
            except Exception as exc:  # Bot API недоступен
                raise HTTPException(503, "бот Telegram сейчас недоступен") from exc
            with self.db() as db:
                token = tg.issue_ticket(db, lang)
            return {
                "token": token,
                "url": f"https://t.me/{bot}?start={token}",
                "expires_in": tg.TICKET_MINUTES * 60,
            }

        @r.get("/api/auth/telegram/status")
        def telegram_status(request: Request, token: str, invite: str | None = None) -> Response:
            """Опрос билета: номер ещё не пришёл — pending; пришёл — вход, cookie сессии;
            билет устарел — 410."""
            if self.telegram is None:
                raise HTTPException(503, "вход через Telegram не настроен (TELEGRAM_BOT_TOKEN)")
            with self.db() as db:
                try:
                    ticket = tg.claim_ticket(db, token)
                except acc.AccessError as exc:
                    raise HTTPException(410, str(exc)) from exc
                if ticket is None:
                    return JSONResponse({"status": "pending"})
                info = {"sub": ticket.telegram_user_id, "phone": ticket.phone, "name": ticket.name}
            session_token, error = self._finish_login(
                info, invite, request.headers.get("user-agent", ""), tg.PROVIDER
            )
            response = JSONResponse({"status": "done", "invite_error": error})
            self._set_cookie(response, session_token)
            return response

        @r.post(WEBHOOK_PATH)
        async def telegram_webhook(request: Request) -> dict[str, bool]:
            """Обновления от Bot API (https); секрет — в заголовке, его ставит setWebhook."""
            given = request.headers.get("x-telegram-bot-api-secret-token", "")
            if self.telegram is None or given != self.webhook_secret():
                raise HTTPException(403, "не бот")
            update = await request.json()
            await run_in_threadpool(self.handle_update, update)
            return {"ok": True}

        @r.post("/api/auth/code")
        def code_login(request: Request, code: str = Body(..., embed=True)) -> dict[str, Any]:
            """Вход по коду доступа к проекту: код действует — в подписанной cookie id кода,
            дальше каждый запрос проверяет, что код не отозван. Учётки не появляется."""
            ip = client_ip(request)
            if self.limiter.blocked(ip):
                raise HTTPException(429, "Слишком много неверных кодов — попробуйте позже")
            with self.db() as db:
                try:
                    row = access_codes.use_code(db, code)
                except acc.AccessError as exc:
                    self.limiter.fail(ip)
                    raise HTTPException(400, str(exc)) from exc
                project = db.get(Project, row.project_id)
                request.session["code"] = str(row.id)
                return {"ok": True, "project": project.slug if project else None}

        @r.post("/api/auth/dev")
        def dev_login(request: Request) -> Response:
            """Вход для разработки: под первым суперпользователем, без Google и письма."""
            if not cfg.dev_login:
                raise HTTPException(403, "вход для разработки выключен")
            email = cfg.superusers[0]
            info = {"sub": email, "email": email, "email_verified": True, "name": ""}
            token, _ = self._finish_login(info, None, request.headers.get("user-agent", ""), "dev")
            response = JSONResponse({"ok": True})
            self._set_cookie(response, token)
            return response

        @r.post("/api/auth/visitor")
        def visitor(request: Request) -> dict[str, bool]:
            if not cfg.visitor:
                raise HTTPException(403, "гостевой вход выключен")
            request.session["visitor"] = True
            return {"visitor": True}

        @r.post("/api/auth/logout")
        def logout(request: Request) -> Response:
            token = request.cookies.get(COOKIE)
            if token:
                with self.db() as db:
                    acc.end_session(db, token)
            request.session.clear()
            response = JSONResponse({"ok": True})
            response.delete_cookie(COOKIE, path="/")
            return response

        @r.post("/api/auth/account-type")
        def account_type(
            request: Request, kind: Literal["client"] = Body(..., embed=True, alias="type")
        ) -> dict[str, Any]:
            """«Мой ремонт» — личное пространство; фирма — /api/auth/firm (с названием)."""
            with self.db() as db:
                who = self.principal(db, request)
                if who is None or who.user is None:
                    raise HTTPException(401, "нужен вход")
                try:
                    acc.set_account_type(db, who.user, kind)
                except acc.AccessError as exc:
                    raise HTTPException(409, str(exc)) from exc
                self._adopt(db, who.user)
                return _user_json(db, who.user)

        @r.post("/api/auth/firm")
        def register_firm(
            request: Request,
            name: str = Body(..., embed=True),
            business: str = Body(..., embed=True),
            city: str = Body("", embed=True),
            phone: str = Body("", embed=True),
        ) -> dict[str, Any]:
            """Регистрация фирмы при первом входе: название, вид, город, телефон."""
            with self.db() as db:
                who = self.principal(db, request)
                if who is None or who.user is None:
                    raise HTTPException(401, "нужен вход")
                try:
                    acc.register_firm(db, who.user, name, business, city, phone)
                except acc.AccessError as exc:
                    raise HTTPException(409, str(exc)) from exc
                self._adopt(db, who.user)
                return _user_json(db, who.user)

        @r.get("/api/invites/{token}")
        def invite_info(token: str) -> dict[str, Any]:
            with self.db() as db:
                try:
                    invite = acc.find_invite(db, token)
                except acc.AccessError as exc:
                    raise HTTPException(404, str(exc)) from exc
                project = acc.project_of(db, invite)
                return {"role": invite.role, "project": project.name if project else None}

        @r.post("/api/invites/{token}/accept")
        def invite_accept(request: Request, token: str) -> dict[str, Any]:
            with self.db() as db:
                who = self.principal(db, request)
                if who is None or who.user is None:
                    raise HTTPException(401, "нужен вход")
                try:
                    invite = acc.accept_invite(db, who.user, token)
                except acc.AccessError as exc:
                    raise HTTPException(409, str(exc)) from exc
                project = acc.project_of(db, invite)
                return {"role": invite.role, "project": project.slug if project else None}

        return r

    def _finish_login(
        self, info: dict[str, Any], invite: str | None, user_agent: str, provider: str = "google"
    ) -> tuple[str, str | None]:
        """Пользователь по ответу провайдера (Google или код на почту), принятие приглашения,
        новая сессия; вернёт токен сессии и ошибку приглашения (если была)."""
        error: str | None = None
        with self.db() as db:
            user = acc.oauth_login(
                db,
                provider,
                str(info["sub"]),
                info.get("email"),
                bool(info.get("email_verified")),
                str(info.get("name") or ""),
                superusers=self.config.superusers,
                phone=info.get("phone"),
            )
            if invite:
                try:
                    acc.accept_invite(db, user, invite)
                except acc.AccessError as exc:
                    error = str(exc)
            self._adopt(db, user)
            return acc.create_session(db, user, user_agent), error
