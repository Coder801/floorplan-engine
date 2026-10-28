"""Доступ и вход: кто какой проект видит и что может, пользователи OAuth, сессии,
приглашения, доступ поддержки, журнал. Правила — docs/database.md, «Доступ» и «Вход».

Функции получают открытую Session и не делают commit, как и repositories.py. Токены
(сессия, приглашение) — случайные строки; в базе только их sha256.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from floorplan_engine.service.db.models import (
    AppUser,
    AuditEvent,
    Invite,
    Membership,
    OAuthAccount,
    Project,
    ProjectMember,
    Studio,
    SupportGrant,
    UserSession,
)

AccountType = Literal["client", "pro"]
# Роль в проекте: из студии (owner, designer, installer), из проекта (client, installer),
# поддержка по support_grant, суперпользователь, гость отладки (visitor)
Role = Literal["owner", "designer", "installer", "client", "support", "superuser", "visitor"]
Action = Literal["view", "answer", "edit_wiring", "invite"]

CAN: dict[Action, frozenset[str]] = {
    "view": frozenset(
        {"owner", "designer", "installer", "client", "support", "superuser", "visitor"}
    ),
    "answer": frozenset({"owner", "designer", "client", "superuser"}),
    "edit_wiring": frozenset({"owner", "designer", "installer", "support", "superuser"}),
    "invite": frozenset({"owner", "designer", "client", "superuser"}),
}
STUDIO_ROLES = frozenset({"owner", "designer", "installer"})
PROJECT_ROLES = frozenset({"client", "installer"})

SESSION_DAYS = 30
INVITE_DAYS = 7
SUPPORT_HOURS = 72


class AccessError(ValueError):
    """Действие нельзя выполнить: сообщение — для пользователя, на русском."""


def now() -> datetime:
    return datetime.now(UTC)


def _aware(t: datetime) -> datetime:
    """SQLite отдаёт время без пояса — считаем его UTC."""
    return t if t.tzinfo is not None else t.replace(tzinfo=UTC)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Principal:
    """Кто делает запрос: пользователь базы или гость отладки (user is None)."""

    user: AppUser | None

    @property
    def visitor(self) -> bool:
        return self.user is None


VISITOR = Principal(None)


def can(role: str | None, action: Action) -> bool:
    return role is not None and role in CAN[action]


# --- Роль в проекте ------------------------------------------------------------------


def project_role(session: Session, who: Principal, project: Project | None) -> Role | None:
    """Роль в проекте или None — проекта не видно. Гость отладки видит всё (только чтение),
    суперпользователь — всё; остальные — по студии, участию в проекте или доступу
    поддержки. Проект вне базы (папка без строки) — только гостю и суперпользователю."""
    if who.user is None:
        return "visitor"
    user = who.user
    if not user.is_active:
        return None
    if user.is_superuser:
        return "superuser"
    if project is None:
        return None
    studio_role = _studio_role(session, user, project.studio_id)
    if studio_role is not None:
        return studio_role
    member_role = session.scalar(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user.id
        )
    )
    if member_role in PROJECT_ROLES:
        return member_role  # type: ignore[return-value]
    if _active_grant(session, project.id, user.id) is not None:
        return "support"
    return None


def _studio_role(session: Session, user: AppUser, studio_id: uuid.UUID) -> Role | None:
    role = session.scalar(
        select(Membership.role).where(
            Membership.studio_id == studio_id, Membership.user_id == user.id
        )
    )
    return role if role in STUDIO_ROLES else None  # type: ignore[return-value]


def _active_grant(
    session: Session, project_id: uuid.UUID, user_id: uuid.UUID
) -> SupportGrant | None:
    grants = session.scalars(
        select(SupportGrant).where(
            SupportGrant.project_id == project_id,
            SupportGrant.user_id == user_id,
            SupportGrant.revoked_at.is_(None),
        )
    ).all()
    t = now()
    return next((g for g in grants if _aware(g.expires_at) > t), None)


def visible_slugs(session: Session, who: Principal, slugs: Collection[str]) -> set[str]:
    """Какие папки проектов из slugs видны: гостю и суперпользователю — все."""
    if who.user is None or who.user.is_superuser:
        return set(slugs) if who.user is None or who.user.is_active else set()
    projects = session.scalars(select(Project).where(Project.slug.in_(list(slugs)))).all()
    return {
        p.slug for p in projects if p.slug is not None and project_role(session, who, p) is not None
    }


def project_by_slug(session: Session, slug: str) -> Project | None:
    return session.scalar(select(Project).where(Project.slug == slug))


# --- Пользователи OAuth и тип учётки -------------------------------------------------


def oauth_login(
    session: Session,
    provider: str,
    provider_user_id: str,
    email: str | None,
    email_verified: bool,
    name: str = "",
    superusers: Collection[str] = (),
) -> AppUser:
    """Пользователь по учётке провайдера; новой учётке — новый пользователь или, если
    провайдер подтвердил email и он уже есть, тот же пользователь. superusers — email
    владельцев платформы (из окружения)."""
    email = email.strip().lower() if email else None
    account = session.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider, OAuthAccount.provider_user_id == provider_user_id
        )
    )
    user = session.get(AppUser, account.user_id) if account is not None else None
    if user is None and email and email_verified:
        user = session.scalar(select(AppUser).where(func.lower(AppUser.email) == email))
    if user is None:
        free = email if email and email_verified else None
        user = AppUser(email=free, name=name)
        session.add(user)
        session.flush()
    if account is None:
        session.add(
            OAuthAccount(
                user_id=user.id, provider=provider, provider_user_id=provider_user_id, email=email
            )
        )
    if not user.name and name:
        user.name = name
    if user.email and user.email.lower() in {s.strip().lower() for s in superusers}:
        user.is_superuser = True
    user.last_login_at = now()
    session.flush()
    audit(session, "login", user=user, payload={"provider": provider})
    return user


def set_account_type(session: Session, user: AppUser, kind: AccountType) -> Studio:
    """Выбор при первом входе: pro — своя студия, client — личное пространство на один
    проект; пользователь — владелец. Выбранный тип не меняется."""
    if user.account_type is not None:
        raise AccessError("тип учётной записи уже выбран")
    user.account_type = kind
    name = user.name or user.email or ("Студия" if kind == "pro" else "Мой проект")
    studio = Studio(name=name, kind="studio" if kind == "pro" else "personal")
    session.add(studio)
    session.flush()
    session.add(Membership(studio_id=studio.id, user_id=user.id, role="owner"))
    session.flush()
    return studio


def own_studio(session: Session, user: AppUser) -> Studio | None:
    """Студия (или личное пространство), где пользователь — владелец."""
    return session.scalar(
        select(Studio)
        .join(Membership, Membership.studio_id == Studio.id)
        .where(Membership.user_id == user.id, Membership.role == "owner")
        .order_by(Studio.created_at)
        .limit(1)
    )


def client_projects(session: Session, user: AppUser) -> int:
    """Сколько проектов у клиента: в личном пространстве и по приглашению."""
    personal = session.scalar(
        select(func.count(Project.id))
        .join(Studio, Studio.id == Project.studio_id)
        .join(Membership, Membership.studio_id == Studio.id)
        .where(Membership.user_id == user.id, Studio.kind == "personal")
    )
    invited = session.scalar(
        select(func.count()).where(ProjectMember.user_id == user.id, ProjectMember.role == "client")
    )
    return int(personal or 0) + int(invited or 0)


def create_project_for(session: Session, user: AppUser, name: str, slug: str) -> Project:
    """Новый проект в своей студии; у клиента — только один проект."""
    studio = own_studio(session, user)
    if studio is None:
        raise AccessError("сначала выберите тип учётной записи")
    if user.account_type == "client" and client_projects(session, user) >= 1:
        raise AccessError("у хозяина квартиры — один проект")
    project = Project(studio_id=studio.id, name=name, slug=slug)
    session.add(project)
    session.flush()
    audit(session, "project_create", user=user, project=project)
    return project


# --- Сессии --------------------------------------------------------------------------


def create_session(session: Session, user: AppUser, user_agent: str = "") -> str:
    """Новая сессия; вернёт токен для cookie (в базе — только его хеш)."""
    token = new_token()
    t = now()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=token_hash(token),
            user_agent=user_agent[:500],
            created_at=t,
            last_seen_at=t,
            expires_at=t + timedelta(days=SESSION_DAYS),
        )
    )
    session.flush()
    return token


def session_user(session: Session, token: str) -> AppUser | None:
    """Пользователь по токену сессии; истёкшая сессия или заблокированный — None."""
    row = session.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    if row is None or _aware(row.expires_at) <= now():
        return None
    user = session.get(AppUser, row.user_id)
    if user is None or not user.is_active:
        return None
    row.last_seen_at = now()
    return user


def end_session(session: Session, token: str) -> None:
    row = session.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    if row is not None:
        session.delete(row)
        session.flush()


def end_all_sessions(session: Session, user: AppUser) -> None:
    for row in session.scalars(select(UserSession).where(UserSession.user_id == user.id)):
        session.delete(row)
    session.flush()


# --- Приглашения ---------------------------------------------------------------------


def create_invite(
    session: Session,
    by: AppUser | None,
    role: str,
    project: Project | None = None,
    studio: Studio | None = None,
    email: str | None = None,
    days: int = INVITE_DAYS,
) -> str:
    """Приглашение в проект (client, installer) или в студию (designer, installer).
    by — кто приглашает (None — суперпользователь из командной строки). Вернёт токен."""
    if (project is None) == (studio is None):
        raise AccessError("приглашение — в проект или в студию")
    if project is not None and role not in PROJECT_ROLES:
        raise AccessError(f"в проект приглашают как {' или '.join(sorted(PROJECT_ROLES))}")
    if studio is not None and role not in {"designer", "installer"}:
        raise AccessError("в студию приглашают как designer или installer")
    if by is not None and not by.is_superuser:
        if project is not None:
            mine = project_role(session, Principal(by), project)
        else:
            assert studio is not None
            mine = _studio_role(session, by, studio.id)
        if not can(mine, "invite"):
            raise AccessError("нет права приглашать")
        if by.account_type == "client" and role != "installer":
            raise AccessError("хозяин квартиры приглашает в проект только монтажника")
    token = new_token()
    session.add(
        Invite(
            project_id=project.id if project else None,
            studio_id=studio.id if studio else None,
            role=role,
            email=email,
            token_hash=token_hash(token),
            invited_by=by.id if by else None,
            expires_at=now() + timedelta(days=days),
        )
    )
    session.flush()
    audit(
        session,
        "invite",
        user=by,
        project=project,
        payload={"role": role, "email": email, "studio": str(studio.id) if studio else None},
    )
    return token


def find_invite(session: Session, token: str) -> Invite:
    """Действующее приглашение по токену; иначе AccessError с причиной."""
    invite = session.scalar(select(Invite).where(Invite.token_hash == token_hash(token)))
    if invite is None or invite.revoked_at is not None:
        raise AccessError("приглашение не найдено или отозвано")
    if invite.accepted_at is not None:
        raise AccessError("приглашение уже принято")
    if _aware(invite.expires_at) <= now():
        raise AccessError("срок приглашения истёк — попросите новое")
    return invite


def accept_invite(session: Session, user: AppUser, token: str) -> Invite:
    """Принять приглашение: ссылка — ключ, email не сверяется (студия видит, кто принял).
    Приглашённый без типа учётки получает его по роли: клиент — client, остальные — pro."""
    invite = find_invite(session, token)
    kind = user.account_type or ("client" if invite.role == "client" else "pro")
    if invite.role == "client" and kind != "client":
        raise AccessError("приглашение для хозяина квартиры, а вход — студии")
    if invite.role != "client" and kind == "client":
        raise AccessError("приглашение для студии или монтажника, а вход — хозяина квартиры")
    if invite.role == "client" and client_projects(session, user) >= 1:
        raise AccessError("у хозяина квартиры уже есть проект")
    user.account_type = kind
    if invite.project_id is not None:
        exists = session.get(ProjectMember, (invite.project_id, user.id))
        if exists is None:
            session.add(
                ProjectMember(
                    project_id=invite.project_id,
                    user_id=user.id,
                    role=invite.role,
                    invited_by=invite.invited_by,
                )
            )
    else:
        assert invite.studio_id is not None
        if session.get(Membership, (invite.studio_id, user.id)) is None:
            session.add(Membership(studio_id=invite.studio_id, user_id=user.id, role=invite.role))
    invite.accepted_by = user.id
    invite.accepted_at = now()
    session.flush()
    project = session.get(Project, invite.project_id) if invite.project_id else None
    audit(session, "invite_accept", user=user, project=project, payload={"role": invite.role})
    return invite


def project_of(session: Session, invite: Invite) -> Project | None:
    return session.get(Project, invite.project_id) if invite.project_id else None


# --- Поддержка и журнал --------------------------------------------------------------


def grant_support(
    session: Session,
    project: Project,
    developer: AppUser,
    by: AppUser,
    reason: str,
    hours: int = SUPPORT_HOURS,
) -> SupportGrant:
    """Владелец студии открывает проект разработчику на срок — чинить баг."""
    if project_role(session, Principal(by), project) not in {"owner", "superuser"}:
        raise AccessError("доступ поддержке выдаёт владелец студии")
    grant = SupportGrant(
        project_id=project.id,
        user_id=developer.id,
        granted_by=by.id,
        reason=reason,
        expires_at=now() + timedelta(hours=hours),
    )
    session.add(grant)
    session.flush()
    audit(session, "support_grant", user=by, project=project, payload={"to": str(developer.id)})
    return grant


def revoke_support(session: Session, project: Project, developer: AppUser) -> None:
    t = now()
    for g in session.scalars(
        select(SupportGrant).where(
            SupportGrant.project_id == project.id,
            SupportGrant.user_id == developer.id,
            SupportGrant.revoked_at.is_(None),
        )
    ):
        g.revoked_at = t
    session.flush()


def audit(
    session: Session,
    action: str,
    user: AppUser | None = None,
    project: Project | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            action=action,
            user_id=user.id if user else None,
            project_id=project.id if project else None,
            payload=payload or {},
        )
    )


def events(session: Session, project: Project, limit: int = 100) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.project_id == project.id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
    )
