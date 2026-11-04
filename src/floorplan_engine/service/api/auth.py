"""Viewer login: Google (OAuth, Authlib) and an e-mail code, cookie sessions, invites, a debug
guest.

Turned on by the environment (SHTROBA_AUTH=on); without it the viewer is open, as before
(locally). Access rules live in db/access.py; this is the web part: routes /api/auth/*,
/api/invites/* and the middleware that checks access to /api/projects/{name}/… (decisions
2026-10-28, docs/database.md, "Login").

Environment:
  SHTROBA_AUTH=on              turn login on
  SHTROBA_SECRET               signing key for the OAuth state cookie (a long random string)
  SHTROBA_PUBLIC_URL           page address: https://… (with /api there) or http://127.0.0.1:5173
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET   Google OAuth client; without it there is no Google button
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM   login code e-mails (mail.py);
                               without SMTP over http (locally) the code goes to the server log,
                               over https there is no code login
  TELEGRAM_BOT_TOKEN           bot for login by phone number (api/telegram.py); without it there
                               is no "Log in with Telegram" button. Over https the bot uses the
                               webhook <SHTROBA_PUBLIC_URL>/api/auth/telegram/webhook, over http
                               (locally) the server polls the Bot API itself
  A project access code (db/access_codes.py) needs no setup: it is issued by the command
  `floorplan-engine access code projects/<name>`, login is /api/auth/code.
  SHTROBA_ACCESS_CODES         permanent access codes "folder=CODE", comma-separated
                               (kv42=ABCD-2345): on start the service writes them to the database
                               (a project without a row gets "no owner"), a revoked one works
                               again; for tests, until codes are issued from the viewer
  SHTROBA_SUPERUSERS           e-mails or phones ("+380…") of platform owners, comma-separated
  SHTROBA_OWNER                e-mail or phone of the owner of folder projects: when they log in
                               and choose "Firm", folders without a database row move into their
                               studio (access.adopt_folders)
  SHTROBA_DEV_LOGIN=1          "Log in for development": login without Google or e-mail as the
                               first SHTROBA_SUPERUSERS address; http only (locally), not production
  SHTROBA_VISITOR=1            "Log in as guest" without an account, for debugging only: sees all
                               projects, read only; forbidden in the Railway "production"
                               environment
  DATABASE_URL                 database (db/session.py)
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from floorplan_engine.service.api import telegram
from floorplan_engine.service.api.admin import PREFIX as ADMIN_PREFIX
from floorplan_engine.service.api.admin import admin_router
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
# No login needed: the login itself, invites (to see what you are invited to), API docs
OPEN_PREFIXES = ("/api/auth/", "/api/invites/")
PRICES_PATH = "/api/prices"  # studio price page (viewer.py): studio accounts only
# Access code guessing: at most CODE_TRIES wrong codes per address in CODE_WINDOW seconds
CODE_TRIES = 20
CODE_WINDOW = 600


class ConfigError(RuntimeError):
    """The login environment is misconfigured: the service does not start."""


@dataclass(frozen=True)
class AuthConfig:
    secret: str
    public_url: str
    google_id: str | None = None
    google_secret: str | None = None
    superusers: tuple[str, ...] = ()
    visitor: bool = False
    dev_login: bool = False  # "Log in for development" as the first superuser
    owner: str | None = None  # SHTROBA_OWNER: whose project folders have no database row
    fixed_codes: tuple[tuple[str, str], ...] = ()  # SHTROBA_ACCESS_CODES: (folder, code)

    @property
    def google(self) -> bool:
        return bool(self.google_id and self.google_secret)

    @property
    def secure(self) -> bool:
        return self.public_url.startswith("https://")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AuthConfig | None:
        """Settings from the environment; None if login is off."""
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
        fixed: list[tuple[str, str]] = []
        for item in env.get("SHTROBA_ACCESS_CODES", "").split(","):
            if not item.strip():
                continue
            slug, sep, code = item.partition("=")
            try:
                if not sep or not slug.strip():
                    raise acc.AccessError("нужно «папка=КОД»")
                fixed.append((slug.strip(), access_codes.normalize_code(code)))
            except acc.AccessError as exc:
                raise ConfigError(f"SHTROBA_ACCESS_CODES — «{item.strip()}»: {exc}") from exc
        return cls(
            secret=secret,
            public_url=public,
            google_id=env.get("GOOGLE_CLIENT_ID") or None,
            google_secret=env.get("GOOGLE_CLIENT_SECRET") or None,
            superusers=superusers,
            visitor=visitor,
            dev_login=dev,
            owner=identity(env["SHTROBA_OWNER"]) if env.get("SHTROBA_OWNER", "").strip() else None,
            fixed_codes=tuple(fixed),
        )


class CodeLimiter:
    """Wrong access codes per client address, in process memory: CODE_TRIES per CODE_WINDOW
    seconds, then 429. A code is 40 bits, so brute force is out of reach anyway, but extra
    attempts are not welcome."""

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
    """Client address: behind a proxy (Railway, Caddy) the first one from X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


def identity(value: str) -> str:
    """Who this is from the environment: a phone as "+380…", an e-mail in lower case (as stored
    for the user)."""
    value = value.strip()
    return tg.normalize_phone(value) if tg.is_phone(value) else value.lower()


def _user_json(db: Session, user: AppUser) -> dict[str, Any]:
    """The user and their workspace: a firm (kind studio, type and city) or personal."""
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
    """Login and access for one FastAPI app."""

    config: AuthConfig
    sessions: sessionmaker[Session]
    oauth: OAuth = field(default_factory=OAuth)
    mailer: Mailer | None = None  # login code e-mails; None means no code login
    telegram: telegram.TelegramApi | None = None  # bot for phone login; None means no button
    folders: Callable[[], Collection[str]] | None = None  # project folders (set by create_viewer)
    limiter: CodeLimiter = field(default_factory=CodeLimiter)  # access code guessing
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
        """The folder owner (SHTROBA_OWNER) logged in or chose an account type: folders without a
        database row go to their studio. Not the owner, no folders or no type chosen yet:
        nothing."""
        owner = self.config.owner
        if owner and self.folders is not None and owner in (user.email, user.phone):
            acc.adopt_folders(db, owner, self.folders())

    def seed_codes(self) -> None:
        """On server start: permanent codes from SHTROBA_ACCESS_CODES go to the database
        (access_codes.ensure_code); a project missing from the database gets a "no owner" row. If
        there is no folder with that name or the code belongs to another project: a warning and
        nothing in the database (an error inside `db()` also rolls back the created project). If two
        processes start at once, the second hits a uniqueness violation: the first has already
        written the code."""
        folders = None if self.folders is None else set(self.folders())
        for slug, code in self.config.fixed_codes:
            if folders is not None and slug not in folders:
                log.warning("SHTROBA_ACCESS_CODES %s: папки проекта нет — код пропущен", slug)
                continue
            try:
                with self.db() as db:
                    project = acc.project_by_slug(db, slug)
                    if project is None:
                        project = acc.create_project_unowned(db, slug, slug)
                    access_codes.ensure_code(db, project, code)
            except acc.AccessError as exc:
                log.warning("SHTROBA_ACCESS_CODES %s: %s", slug, exc)
                continue
            except IntegrityError:
                log.info("Постоянный код доступа к проекту %s записал другой процесс", slug)
                continue
            log.info("Постоянный код доступа к проекту %s — в базе", slug)

    # --- Telegram ------------------------------------------------------------------------

    def bot_name(self) -> str:
        """Bot name for the t.me/<name> link, fetched once from the Bot API."""
        assert self.telegram is not None
        if self._bot_name is None:
            self._bot_name = self.telegram.get_me()
        return self._bot_name

    def webhook_secret(self) -> str:
        return acc.token_hash(f"telegram:{self.config.secret}")

    def handle_update(self, update: dict[str, Any]) -> None:
        """Bot update (webhook or polling) goes to the login rules, in its own transaction."""
        assert self.telegram is not None
        with self.db() as db:
            telegram.handle_update(db, self.telegram, update)

    def start_telegram(self) -> None:
        """On server start: a webhook over https, background Bot API polling over http."""
        if self.telegram is None:
            return
        if self.config.secure:
            try:
                self.telegram.set_webhook(
                    self.config.public_url + WEBHOOK_PATH, self.webhook_secret()
                )
            except Exception as exc:  # network: login without Telegram, everything else works
                log.warning("Telegram setWebhook: %s", exc)
        else:
            telegram.start_polling(self.telegram, self.handle_update)

    # --- who is calling ----------------------------------------------------------------

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
        """Logged in by code: the code's project (folder and name) for the header and opening the
        project.
        """
        if who is None or not who.by_code:
            return None
        project = db.get(Project, who.code_project)
        if project is None:
            return None
        return {"project": project.slug, "name": project.name}

    def check(self, request: Request) -> Response | None:
        """API request check; None means let it through. Not logged in gives 401, no access to the
        project gives 404 (other people's projects are not revealed), no permission gives 403."""
        path = request.url.path
        if not path.startswith("/api/") or path.startswith(OPEN_PREFIXES):
            return None
        with self.db() as db:
            who = self.principal(db, request)
            if who is None:
                return JSONResponse({"detail": "нужен вход"}, status_code=401)
            if path.startswith(ADMIN_PREFIX):  # platform admin (api/admin.py): superuser only
                if who.user is None or not who.user.is_superuser or not who.user.is_active:
                    return JSONResponse(
                        {"detail": "только для владельца платформы"}, status_code=403
                    )
                request.state.admin = who.user.id
                return None
            parts = path.split("/")  # ["", "api", "projects", name, …]
            if path == PRICES_PATH:  # the price list of the caller's own studio
                return self._prices(db, who, request)
            if len(parts) < 4 or parts[2] != "projects" or not parts[3]:
                return None
            project = acc.project_by_key(db, parts[3], who)
            role = acc.project_role(db, who, project)
            if not acc.can(role, "view"):
                return JSONResponse({"detail": f"проекта {parts[3]} нет"}, status_code=404)
            action: acc.Action = "view"
            if request.method == "POST" and parts[-1] == "wiring":
                action = "edit_wiring"
            elif request.method == "POST" and parts[-1] == "variant":
                action = "choose_variant"
            elif request.method == "POST" and parts[-1] == "answers":
                action = "answer"
            if not acc.can(role, action):
                return JSONResponse({"detail": "нет права на это действие"}, status_code=403)
            if role == "support" and project is not None:
                payload = {"path": path}
                acc.audit(db, "support_access", user=who.user, project=project, payload=payload)
            request.state.role = role
            # Where the project folder is: its studio folder; a folder without a row — the root
            request.state.folder = (
                acc.studio_folder(project.studio) if project is not None else acc.ROOT_FOLDER
            )
        return None

    def _prices(self, db: Session, who: acc.Principal, request: Request) -> Response | None:
        """Studio price list: a studio account edits the list of its own studio (prices.yaml in
        the studio folder); a superuser outside a studio and the debug guest — the root list (the
        guest only reads)."""
        user = who.user
        space = acc.user_space(db, user) if user is not None else None
        if user is not None and (
            user.is_superuser or (user.account_type == "pro" and space is not None)
        ):
            edit = True
        elif who.visitor and request.method == "GET":
            edit = False
        else:
            return JSONResponse({"detail": "прайс — только для студии"}, status_code=403)
        request.state.edit_prices = edit
        request.state.folder = acc.studio_folder(space) if space is not None else acc.ROOT_FOLDER
        request.state.studio_id = space.id if space is not None else None  # viewer_db
        return None

    def project_folders(self, request: Request, root_names: Collection[str]) -> dict[str, str]:
        """Projects the caller sees: folder name → studio folder relative to the root. Database
        projects by their studio; folders in the root without a row (root_names) — for the guest
        and a superuser."""
        with self.db() as db:
            who = self.principal(db, request)
            if who is None:
                return {}
            shown = {
                p.slug: acc.studio_folder(p.studio)
                for p in db.scalars(acc.visible_projects(db, who))
                if p.slug is not None
            }
            for name in acc.visible_slugs(db, who, root_names):
                shown.setdefault(name, acc.ROOT_FOLDER)
            return shown

    # --- wiring into the app -----------------------------------------------------------

    def install(self, app: FastAPI) -> None:
        auth = self

        @app.middleware("http")
        async def guard(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            denied = await run_in_threadpool(auth.check, request)
            return denied if denied is not None else await call_next(request)

        # Outside the guard: the guard reads request.session (debug guest, invite)
        app.add_middleware(
            SessionMiddleware,
            secret_key=self.config.secret,
            session_cookie="shtroba_oauth",
            same_site="lax",
            https_only=self.config.secure,
        )
        app.include_router(self.router())
        app.include_router(admin_router(self))
        if self.config.fixed_codes:
            app.router.on_startup.append(self.seed_codes)
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
        self._session_routes(r)
        self._email_routes(r)
        self._telegram_routes(r)
        self._code_routes(r)
        self._account_routes(r)
        self._invite_routes(r)
        return r

    def _session_routes(self, r: APIRouter) -> None:
        """Who is logged in."""
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

    def _email_routes(self, r: APIRouter) -> None:
        """Login with a code by e-mail."""

        @r.post("/api/auth/email/start")
        def email_start(
            email: str = Body(..., embed=True), lang: str = Body("ru", embed=True)
        ) -> dict[str, Any]:
            """Code by e-mail. Does not reveal whether the user exists: the account appears on
            login.
            """
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
            """Login by code: the user (the same as with Google if the e-mail matches), invite,
            cookie session."""
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

    def _telegram_routes(self, r: APIRouter) -> None:
        """Login with Telegram."""

        @r.post("/api/auth/telegram/start")
        def telegram_start(lang: str = Body("ru", embed=True)) -> dict[str, Any]:
            """Login ticket and the bot link; the page opens it and polls status."""
            if self.telegram is None:
                raise HTTPException(503, "вход через Telegram не настроен (TELEGRAM_BOT_TOKEN)")
            try:
                bot = self.bot_name()
            except Exception as exc:  # Bot API unavailable
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
            """Ticket poll: no number yet gives pending; once it arrives, login and a session
            cookie;
            an expired ticket gives 410."""
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
            """Updates from the Bot API (https); the secret is in a header set by setWebhook."""
            given = request.headers.get("x-telegram-bot-api-secret-token", "")
            if self.telegram is None or given != self.webhook_secret():
                raise HTTPException(403, "не бот")
            update = await request.json()
            await run_in_threadpool(self.handle_update, update)
            return {"ok": True}

    def _code_routes(self, r: APIRouter) -> None:
        """Login with an access code, development logins, logout."""
        cfg = self.config

        @r.post("/api/auth/code")
        def code_login(request: Request, code: str = Body(..., embed=True)) -> dict[str, Any]:
            """Login by project access code: if the code is valid, its id goes into a signed cookie,
            and every
            later request checks that the code was not revoked. No account is created."""
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
            """Development login: as the first superuser, without Google or e-mail."""
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

    def _account_routes(self, r: APIRouter) -> None:
        """Account type and firm registration."""

        @r.post("/api/auth/account-type")
        def account_type(
            request: Request, kind: Literal["client"] = Body(..., embed=True, alias="type")
        ) -> dict[str, Any]:
            """Choose "Мой ремонт", the personal workspace; a firm uses /api/auth/firm."""
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
            """Firm registration on first login: name, kind, city, phone."""
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

    def _invite_routes(self, r: APIRouter) -> None:
        """Invites."""

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

    def _finish_login(
        self, info: dict[str, Any], invite: str | None, user_agent: str, provider: str = "google"
    ) -> tuple[str, str | None]:
        """User from the provider answer (Google or e-mail code), invite acceptance, a new session;
        returns the session token and the invite error (if any)."""
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
