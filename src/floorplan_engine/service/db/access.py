"""Access and login: who sees which project and what they may do, OAuth users, sessions, invites,
support access, audit log. Rules: docs/database.md, "Access" and "Login".

Functions take an open Session and do not commit, like repositories.py. Tokens (session,
invite) are random strings; only their sha256 is stored.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Select, false, func, or_, select
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
# Project role: from the studio (owner, designer, installer), from the project (client, installer),
# support via support_grant, superuser, debug guest (visitor), login by an access code to one
# project (db/access_codes.py): a view code (viewer) or a client code (client_code) — the client
# sets the flat up without an account: answers and the variant, nothing else
Role = Literal[
    "owner",
    "designer",
    "installer",
    "client",
    "support",
    "superuser",
    "visitor",
    "viewer",
    "client_code",
]
CodeRole = Literal["viewer", "client_code"]
CODE_ROLES: tuple[CodeRole, ...] = ("viewer", "client_code")
Action = Literal["view", "answer", "review", "edit_wiring", "choose_variant", "invite", "manage"]

CAN: dict[Action, frozenset[str]] = {
    "view": frozenset(
        {
            "owner",
            "designer",
            "installer",
            "client",
            "support",
            "superuser",
            "visitor",
            "viewer",
            "client_code",
        }
    ),
    "answer": frozenset({"owner", "designer", "client", "client_code", "superuser"}),
    # Take a client answer into account or send it back with a comment (decision 2026-11-11):
    # the studio that leads the project
    "review": frozenset({"owner", "designer", "superuser"}),
    "edit_wiring": frozenset({"owner", "designer", "installer", "support", "superuser"}),
    # Wiring variant and the setup wizard (docs/wiring-variants.md): the studio, the owner of
    # "Мой ремонт" and, since 2026-11-11, a studio client — it is their flat, by invite or by a
    # client code (client_code). Routes stay with whoever edits them (edit_wiring); a view code
    # (viewer) only views
    "choose_variant": frozenset(
        {"owner", "designer", "installer", "client", "client_code", "support", "superuser"}
    ),
    "invite": frozenset({"owner", "designer", "client", "superuser"}),
    # Service API (api/app.py): model upload, starting analysis, project deletion. Not a limit on
    # tokens: anyone can own a studio (docs/status.md, "Техдолг")
    "manage": frozenset({"owner", "designer", "superuser"}),
}
STUDIO_ROLES = frozenset({"owner", "designer", "installer"})
# The client side (decision 2026-11-11): sees and answers only the questions asked of the client
# and the panel settings (pipeline.answers.for_client), never the studio's questions
CLIENT_SIDE = frozenset({"client", "client_code", "viewer"})
PROJECT_ROLES = frozenset({"client", "installer"})

SESSION_DAYS = 30
INVITE_DAYS = 7
SUPPORT_HOURS = 72


class AccessError(ValueError):
    """The action cannot be performed: the message is for the user, in Russian."""


def now() -> datetime:
    return datetime.now(UTC)


def aware(t: datetime) -> datetime:
    """SQLite returns time without a zone: treat it as UTC."""
    return t if t.tzinfo is not None else t.replace(tzinfo=UTC)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Principal:
    """Who makes the request: a database user, someone logged in by an access code (user is None,
    code_project is the code's project) or a debug guest (neither)."""

    user: AppUser | None
    code_project: uuid.UUID | None = None
    code_role: CodeRole = "viewer"  # what the code allows (access_codes.issue_code)
    code_label: str = ""  # whom the code was given to: the author of answers made with it

    @property
    def visitor(self) -> bool:
        return self.user is None and self.code_project is None

    @property
    def by_code(self) -> bool:
        return self.user is None and self.code_project is not None


VISITOR = Principal(None)


def can(role: str | None, action: Action) -> bool:
    return role is not None and role in CAN[action]


# --- Project role ----------------------------------------------------------------------


def project_role(session: Session, who: Principal, project: Project | None) -> Role | None:
    """Project role, or None if the project is not visible. A debug guest sees everything (read
    only),
    a superuser everything; someone logged in by code only the code's project, with the code's
    role (viewer reads, client_code also answers and chooses the variant);
    everyone else by studio, project membership or support access. A project outside the
    database (a folder without a row) is visible only to a guest and a superuser."""
    if who.by_code:
        return who.code_role if project is not None and project.id == who.code_project else None
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
    return next((g for g in grants if aware(g.expires_at) > t), None)


def visible_projects(session: Session, who: Principal) -> Select[Project]:
    """Projects the caller sees — one query by the keys, the same rule as project_role: a guest
    and a superuser see all, someone logged in by code the code's project; everyone else the
    projects of their workspace (membership → project.studio_id), the projects they are
    members of (project_member) and those under an active support grant."""
    query = select(Project)
    if who.by_code:
        return query.where(Project.id == who.code_project)
    if who.user is None:
        return query
    user = who.user
    if not user.is_active:
        return query.where(false())
    if user.is_superuser:
        return query
    studios = select(Membership.studio_id).where(
        Membership.user_id == user.id, Membership.role.in_(STUDIO_ROLES)
    )
    members = select(ProjectMember.project_id).where(
        ProjectMember.user_id == user.id, ProjectMember.role.in_(PROJECT_ROLES)
    )
    grants = select(SupportGrant.project_id).where(
        SupportGrant.user_id == user.id,
        SupportGrant.revoked_at.is_(None),
        SupportGrant.expires_at > now(),
    )
    return query.where(
        or_(Project.studio_id.in_(studios), Project.id.in_(members), Project.id.in_(grants))
    )


def visible_slugs(session: Session, who: Principal, slugs: Collection[str]) -> set[str]:
    """Which project folders from slugs are visible (visible_projects): a guest and an active
    superuser also see folders without a database row."""
    if who.user is None and not who.by_code:
        return set(slugs)
    if who.user is not None and who.user.is_superuser and who.user.is_active:
        return set(slugs)
    query = visible_projects(session, who).where(Project.slug.in_(list(slugs)))
    return {p.slug for p in session.scalars(query) if p.slug is not None}


def project_by_slug(session: Session, slug: str, studio: Studio | None = None) -> Project | None:
    """A project by its name: in a studio, or in the whole database if the name is unique there
    (several studios with the same name — AccessError: say which studio)."""
    query = select(Project).where(Project.slug == slug)
    if studio is not None:
        query = query.where(Project.studio_id == studio.id)
    rows = session.scalars(query.limit(2)).all()
    if len(rows) > 1:
        raise AccessError(f"проектов {slug} несколько, в разных студиях — укажите студию или id")
    return rows[0] if rows else None


def project_by_key(session: Session, key: str, who: Principal | None = None) -> Project | None:
    """A project from an address: its id; an old link by name (slug) still opens — among the
    projects the caller sees (who), and only if the name is unique there."""
    try:
        return session.get(Project, uuid.UUID(key))
    except ValueError:
        pass
    if who is None:
        try:
            return project_by_slug(session, key)
        except AccessError:
            return None
    rows = session.scalars(visible_projects(session, who).where(Project.slug == key).limit(2)).all()
    return rows[0] if len(rows) == 1 else None


# --- OAuth users and account type ----------------------------------------------------


def oauth_login(
    session: Session,
    provider: str,
    provider_user_id: str,
    email: str | None,
    email_verified: bool,
    name: str = "",
    superusers: Collection[str] = (),
    phone: str | None = None,
) -> AppUser:
    """User by provider account; a new account gets a new user or, if the provider confirmed an
    e-mail or phone (phone, "+380…", Telegram login) that already exists, the same user.
    superusers are e-mails and phones of the platform owners (from the environment)."""
    email = email.strip().lower() if email else None
    account = session.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider, OAuthAccount.provider_user_id == provider_user_id
        )
    )
    user = session.get(AppUser, account.user_id) if account is not None else None
    if user is None and email and email_verified:
        user = session.scalar(select(AppUser).where(func.lower(AppUser.email) == email))
    if user is None and phone:
        user = session.scalar(select(AppUser).where(AppUser.phone == phone))
    if user is None:
        free = email if email and email_verified else None
        user = AppUser(email=free, phone=phone, name=name)
        session.add(user)
        session.flush()
    if phone and not user.phone:
        user.phone = phone
    if account is None:
        session.add(
            OAuthAccount(
                user_id=user.id, provider=provider, provider_user_id=provider_user_id, email=email
            )
        )
    if not user.name and name:
        user.name = name
    owners = {s.strip().lower() for s in superusers}
    if (user.email and user.email.lower() in owners) or (user.phone and user.phone in owners):
        user.is_superuser = True
    user.last_login_at = now()
    session.flush()
    audit(session, "login", user=user, payload={"provider": provider})
    return user


def set_account_type(session: Session, user: AppUser, kind: AccountType) -> Studio:
    """Workspace on first login: client is personal ("Мой ремонт", one project), pro is a firm
    (registration with name and kind, register_firm); the user is the owner. The workspace type is
    studio.kind; the user's account_type is a hint for the start screen; the chosen type never
    changes."""
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


# Firm kind at registration: design or project, electrical installation, renovation and
# construction, private tradesperson
FIRM_KINDS = ("design", "electric", "construction", "master")
PHONE_RE = re.compile(r"^\+?[\d\s()\-]{5,40}$")


def register_firm(
    session: Session, user: AppUser, name: str, business: str, city: str = "", phone: str = ""
) -> Studio:
    """Firm registration on first login (type pro): name, kind, city and phone; the user is the
    owner. One workspace per person (several firms later)."""
    name, city, phone = name.strip(), city.strip(), phone.strip()
    if not name:
        raise AccessError("Укажите название фирмы")
    if len(name) > 200:
        raise AccessError("Название фирмы — не длиннее 200 символов")
    if business not in FIRM_KINDS:
        raise AccessError("Выберите, чем занимается фирма")
    if len(city) > 100:
        raise AccessError("Город — не длиннее 100 символов")
    if phone and not PHONE_RE.match(phone):
        raise AccessError("Телефон — цифры, пробелы, скобки и «+»")
    space = user_space(session, user)
    if space is not None:
        raise AccessError(f"Вы уже в «{space.name}»")
    studio = set_account_type(session, user, "pro")
    studio.name, studio.business, studio.city, studio.phone = name, business, city, phone
    session.flush()
    audit(session, "firm_register", user=user, payload={"business": business})
    return studio


def user_space(session: Session, user: AppUser) -> Studio | None:
    """The user's one workspace (membership.user_id is unique): their firm or "Мой ремонт", or
    the firm where they are an employee."""
    return session.scalar(
        select(Studio)
        .join(Membership, Membership.studio_id == Studio.id)
        .where(Membership.user_id == user.id)
    )


def own_studio(session: Session, user: AppUser) -> Studio | None:
    """The user's workspace if they are its owner: their firm or "Мой ремонт"."""
    return session.scalar(
        select(Studio)
        .join(Membership, Membership.studio_id == Studio.id)
        .where(Membership.user_id == user.id, Membership.role == "owner")
    )


def client_projects(session: Session, user: AppUser) -> int:
    """How many projects a client has: in the personal workspace and by invite."""
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


# studio.kind of projects written to the database from the command line before the owner logs in
UNOWNED_KIND = "unowned"


# studio.folder of the studio that owns the viewer root (the operator's projects/)
ROOT_FOLDER = ""


def studio_folder(studio: Studio) -> str:
    """Folder of the studio's projects relative to the viewer root, with its prices.yaml and
    studio.yaml: "" is the root itself (the operator's projects/ and "no owner" projects),
    otherwise the studio's own folder named by its id. Studios do not share price lists."""
    if studio.kind == UNOWNED_KIND:
        return ROOT_FOLDER
    return studio.folder if studio.folder is not None else str(studio.id)


def claim_root(session: Session, studio: Studio) -> None:
    """The studio takes the viewer root: project folders lying in the root become its projects
    (adopt_folders, `access link`). The root has one owner, and a studio with projects in its own
    folder does not move."""
    if studio.folder == ROOT_FOLDER:
        return
    other = session.scalar(
        select(Studio).where(
            Studio.folder == ROOT_FOLDER, Studio.kind != UNOWNED_KIND, Studio.id != studio.id
        )
    )
    if other is not None:
        raise AccessError(f"папка проектов в корне уже у «{other.name}»")
    if session.scalar(select(func.count(Project.id)).where(Project.studio_id == studio.id)):
        raise AccessError(f"у «{studio.name}» уже есть проекты в своей папке")
    studio.folder = ROOT_FOLDER
    session.flush()


def unowned_studio(session: Session) -> Studio:
    """The "no owner" studio (one per database, no members): projects written from the command line
    before the owner logged in end up here (`access code`, `access link` without --owner). When
    the owner (SHTROBA_OWNER) logs in, adopt_folders moves them to the owner."""
    studio = session.scalar(select(Studio).where(Studio.kind == UNOWNED_KIND))
    if studio is None:
        studio = Studio(name="Без владельца", kind=UNOWNED_KIND, folder=ROOT_FOLDER)
        session.add(studio)
        session.flush()
    return studio


def create_project_unowned(session: Session, name: str, slug: str) -> Project:
    """Project row without an owner, so an access code can be issued before the owner logs in."""
    studio = unowned_studio(session)
    if project_by_slug(session, slug, studio) is not None:
        raise AccessError(f"проект {slug} уже в базе")
    project = Project(studio_id=studio.id, name=name, slug=slug)
    session.add(project)
    session.flush()
    audit(session, "project_create", project=project, payload={"unowned": True})
    return project


def create_project_for(session: Session, user: AppUser, name: str, slug: str) -> Project:
    """New project in the user's own studio; a client may have only one project."""
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


# --- Sessions ------------------------------------------------------------------------


def adopt_folders(
    session: Session, owner: str, slugs: Collection[str]
) -> tuple[list[str], str | None]:
    """Project folders in the viewer root without a database row and "no owner" projects
    (create_project_unowned, also in the root) move into the owner's studio, which takes the root
    (claim_root). The owner is `SHTROBA_OWNER`, an e-mail or a phone "+380…"; called on login,
    `api/auth.Auth._adopt`. Calling it again changes nothing. Returns the linked slugs and the
    reason if linking is impossible: the owner has not logged in yet, has not chosen an account
    type, has "Мой ремонт" with its single project, or the root belongs to another studio."""
    owner = owner.strip().lower()
    user = session.scalar(
        select(AppUser).where(or_(func.lower(AppUser.email) == owner, AppUser.phone == owner))
    )
    if user is None:
        return [], f"нет пользователя {owner} — пусть сначала войдёт"
    studio = own_studio(session, user)
    if studio is None:
        return [], f"{owner} ещё не выбрал тип учётной записи"
    taken = set(session.scalars(select(Project.slug).where(Project.slug.in_(list(slugs)))))
    new = sorted(set(slugs) - taken)
    unowned = session.scalars(
        select(Project)
        .join(Studio, Studio.id == Project.studio_id)
        .where(Studio.kind == UNOWNED_KIND, Project.slug.in_(list(slugs)))
        .order_by(Project.slug)
    ).all()
    if not new and not unowned:
        return [], None
    try:
        claim_root(session, studio)
    except AccessError as exc:
        return [], str(exc)
    linked: list[str] = []
    for slug in new:
        try:
            create_project_for(session, user, slug, slug)
        except AccessError as exc:
            return linked, str(exc)
        linked.append(slug)
    for project in unowned:
        if user.account_type == "client" and client_projects(session, user) >= 1:
            return linked, "у хозяина квартиры — один проект"
        project.studio_id = studio.id
        session.flush()
        audit(session, "project_adopt", user=user, project=project)
        linked.append(project.slug or project.name)
    return linked, None


def create_session(session: Session, user: AppUser, user_agent: str = "") -> str:
    """New session; returns the token for the cookie (only its hash is stored)."""
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
    """User by session token; None for an expired session or a blocked user."""
    row = session.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    if row is None or aware(row.expires_at) <= now():
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


# --- Invites -------------------------------------------------------------------------


def create_invite(
    session: Session,
    by: AppUser | None,
    role: str,
    project: Project | None = None,
    studio: Studio | None = None,
    email: str | None = None,
    days: int = INVITE_DAYS,
) -> str:
    """Invite to a project (client, installer) or to a studio (designer, installer).
    by is who invites (None means a superuser from the command line). Returns the token."""
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
    """Valid invite by token; otherwise AccessError with the reason."""
    invite = session.scalar(select(Invite).where(Invite.token_hash == token_hash(token)))
    if invite is None or invite.revoked_at is not None:
        raise AccessError("приглашение не найдено или отозвано")
    if invite.accepted_at is not None:
        raise AccessError("приглашение уже принято")
    if aware(invite.expires_at) <= now():
        raise AccessError("срок приглашения истёк — попросите новое")
    return invite


def accept_invite(session: Session, user: AppUser, token: str) -> Invite:
    """Accept an invite: the link is the key, the e-mail is not checked (the studio sees who
    accepted). An invitee without an account type gets one by role: a client gets client, the
    rest get pro."""
    invite = find_invite(session, token)
    kind = user.account_type or ("client" if invite.role == "client" else "pro")
    if invite.role == "client" and kind != "client":
        raise AccessError("приглашение для хозяина квартиры, а вход — студии")
    if invite.role != "client" and kind == "client":
        raise AccessError("приглашение для студии или монтажника, а вход — хозяина квартиры")
    if invite.role == "client" and client_projects(session, user) >= 1:
        raise AccessError("у хозяина квартиры уже есть проект")
    space = user_space(session, user) if invite.studio_id is not None else None
    if space is not None and space.id != invite.studio_id:
        raise AccessError(f"Вы уже в «{space.name}» — в другую фирму нельзя")
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


# --- Support and audit log -----------------------------------------------------------


def grant_support(
    session: Session,
    project: Project,
    developer: AppUser,
    by: AppUser,
    reason: str,
    hours: int = SUPPORT_HOURS,
) -> SupportGrant:
    """The studio owner opens a project to a developer for a limited time, to fix a bug."""
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
