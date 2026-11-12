"""Platform admin (decision 2026-11-03, docs/database.md, "Admin"): what the superuser sees and
changes — studios, users, projects, members, invites, access codes, support, the audit log.

Changes go through the same rules as everywhere (access.py, access_codes.py): one workspace per
person, a client has one project, a studio keeps an owner. Every change is in the audit log with
the admin as its author. Functions take an open Session and do not commit, like access.py; views
return plain data for the API (api/admin.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from floorplan_engine.service.db.access import (
    PROJECT_ROLES,
    STUDIO_ROLES,
    AccessError,
    audit,
    aware,
    client_projects,
    end_all_sessions,
    now,
    studio_folder,
    user_space,
)
from floorplan_engine.service.db.models import (
    AccessCode,
    AppUser,
    AuditEvent,
    Feedback,
    Invite,
    Membership,
    OAuthAccount,
    Project,
    ProjectMember,
    Studio,
    SupportGrant,
    UserSession,
)

EVENTS_LIMIT = 200


def _time(t: datetime | None) -> str | None:
    return aware(t).isoformat() if t is not None else None


def _state(
    expires_at: datetime, revoked_at: datetime | None, accepted_at: datetime | None = None
) -> str:
    """State of an invite, a code or a support grant: accepted | revoked | active | expired."""
    if accepted_at is not None:
        return "accepted"
    if revoked_at is not None:
        return "revoked"
    return "active" if aware(expires_at) > now() else "expired"


def get(session: Session, model: type[Any], id_: str) -> Any:
    """Row by id; LookupError (→ 404) for a malformed or unknown id."""
    try:
        row = session.get(model, uuid.UUID(id_))
    except ValueError:
        row = None
    if row is None:
        raise LookupError(f"{model.__tablename__} {id_} не найден")
    return row


# --- Views -----------------------------------------------------------------------------


def user_brief(user: AppUser) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "account_type": user.account_type,
        "superuser": user.is_superuser,
        "active": user.is_active,
        "last_login": _time(user.last_login_at),
        "created": _time(user.created_at),
    }


def studio_brief(studio: Studio) -> dict[str, Any]:
    return {
        "id": str(studio.id),
        "name": studio.name,
        "kind": studio.kind,
        "business": studio.business,
        "city": studio.city,
        "phone": studio.phone,
        "folder": studio_folder(studio),
        "created": _time(studio.created_at),
    }


def project_brief(project: Project) -> dict[str, Any]:
    return {
        "id": str(project.id),
        "name": project.name,
        "slug": project.slug,
        "studio": {"id": str(project.studio_id), "name": project.studio.name},
        "state": project.state,
        "created": _time(project.created_at),
    }


def summary(session: Session) -> dict[str, int]:
    """Counts for the admin start page."""

    def count(model: type[Any], *where: Any) -> int:
        return int(session.scalar(select(func.count()).select_from(model).where(*where)) or 0)

    return {
        "studios": count(Studio, Studio.kind == "studio"),
        "personal": count(Studio, Studio.kind == "personal"),
        "users": count(AppUser),
        "projects": count(Project),
        "sessions": count(UserSession, UserSession.expires_at > now()),
        "feedback_new": count(Feedback, Feedback.status == "new"),  # db/feedback.py
    }


def studios(session: Session) -> list[dict[str, Any]]:
    members = dict(
        session.execute(
            select(Membership.studio_id, func.count()).group_by(Membership.studio_id)
        ).all()
    )
    projects = dict(
        session.execute(select(Project.studio_id, func.count()).group_by(Project.studio_id)).all()
    )
    return [
        {**studio_brief(s), "members": members.get(s.id, 0), "projects": projects.get(s.id, 0)}
        for s in session.scalars(select(Studio).order_by(Studio.created_at))
    ]


def studio_detail(session: Session, studio: Studio) -> dict[str, Any]:
    rows = session.execute(
        select(Membership, AppUser)
        .join(AppUser, AppUser.id == Membership.user_id)
        .where(Membership.studio_id == studio.id)
        .order_by(Membership.created_at)
    ).all()
    invites = session.scalars(
        select(Invite).where(Invite.studio_id == studio.id).order_by(Invite.created_at.desc())
    )
    return {
        **studio_brief(studio),
        "members": [
            {"user": user_brief(u), "role": m.role, "since": _time(m.created_at)} for m, u in rows
        ],
        "projects": [
            project_brief(p)
            for p in session.scalars(
                select(Project).where(Project.studio_id == studio.id).order_by(Project.slug)
            )
        ],
        "invites": [_invite(session, i) for i in invites],
    }


def users(session: Session, q: str = "") -> list[dict[str, Any]]:
    """Users, newest first; q looks in the name, e-mail and phone."""
    query = select(AppUser).order_by(AppUser.created_at.desc())
    if q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(AppUser.name).like(like),
                func.lower(AppUser.email).like(like),
                AppUser.phone.like(like),
            )
        )
    out = []
    for u in session.scalars(query):
        space = user_space(session, u)
        out.append({**user_brief(u), "space": None if space is None else studio_brief(space)})
    return out


def user_detail(session: Session, user: AppUser) -> dict[str, Any]:
    space = user_space(session, user)
    role = session.scalar(select(Membership.role).where(Membership.user_id == user.id))
    member = session.execute(
        select(ProjectMember, Project)
        .join(Project, Project.id == ProjectMember.project_id)
        .where(ProjectMember.user_id == user.id)
    ).all()
    sessions = session.scalars(
        select(UserSession)
        .where(UserSession.user_id == user.id, UserSession.expires_at > now())
        .order_by(UserSession.last_seen_at.desc())
    )
    return {
        **user_brief(user),
        "space": None if space is None else {**studio_brief(space), "role": role},
        "projects": [{**project_brief(p), "role": m.role} for m, p in member],
        "providers": sorted(
            set(
                session.scalars(
                    select(OAuthAccount.provider).where(OAuthAccount.user_id == user.id)
                )
            )
        ),
        "sessions": [
            {
                "id": str(s.id),
                "agent": s.user_agent,
                "created": _time(s.created_at),
                "seen": _time(s.last_seen_at),
            }
            for s in sessions
        ],
    }


def projects(session: Session) -> list[dict[str, Any]]:
    members = dict(
        session.execute(
            select(ProjectMember.project_id, func.count()).group_by(ProjectMember.project_id)
        ).all()
    )
    return [
        {**project_brief(p), "members": members.get(p.id, 0)}
        for p in session.scalars(select(Project).order_by(Project.slug))
    ]


def _invite(session: Session, i: Invite) -> dict[str, Any]:
    accepted = session.get(AppUser, i.accepted_by) if i.accepted_by else None
    return {
        "id": str(i.id),
        "role": i.role,
        "email": i.email,
        "state": _state(i.expires_at, i.revoked_at, i.accepted_at),
        "created": _time(i.created_at),
        "expires": _time(i.expires_at),
        "accepted_by": user_brief(accepted) if accepted is not None else None,
    }


def project_detail(session: Session, project: Project) -> dict[str, Any]:
    rows = session.execute(
        select(ProjectMember, AppUser)
        .join(AppUser, AppUser.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project.id)
        .order_by(ProjectMember.created_at)
    ).all()
    codes = session.scalars(
        select(AccessCode)
        .where(AccessCode.project_id == project.id)
        .order_by(AccessCode.created_at.desc())
    )
    invites = session.scalars(
        select(Invite).where(Invite.project_id == project.id).order_by(Invite.created_at.desc())
    )
    grants = session.execute(
        select(SupportGrant, AppUser)
        .join(AppUser, AppUser.id == SupportGrant.user_id)
        .where(SupportGrant.project_id == project.id)
        .order_by(SupportGrant.created_at.desc())
    ).all()
    return {
        **project_brief(project),
        "members": [
            {"user": user_brief(u), "role": m.role, "since": _time(m.created_at)} for m, u in rows
        ],
        "codes": [
            {
                "id": str(c.id),
                "label": c.label,
                "role": c.role,
                "state": _state(c.expires_at, c.revoked_at),
                "uses": c.uses,
                "created": _time(c.created_at),
                "expires": _time(c.expires_at),
                "last_used": _time(c.last_used_at),
            }
            for c in codes
        ],
        "invites": [_invite(session, i) for i in invites],
        "support": [
            {
                "user": user_brief(u),
                "reason": g.reason,
                "state": _state(g.expires_at, g.revoked_at),
                "expires": _time(g.expires_at),
            }
            for g, u in grants
        ],
    }


def events(
    session: Session,
    project: Project | None = None,
    user: AppUser | None = None,
    limit: int = EVENTS_LIMIT,
) -> list[dict[str, Any]]:
    """Audit log, newest first: all, of a project or of a user (as the author). People named in
    the payload by id ("user", "to") come back as `subject` with a name, studios as `studio`."""
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(min(limit, 1000))
    if project is not None:
        query = query.where(AuditEvent.project_id == project.id)
    if user is not None:
        query = query.where(AuditEvent.user_id == user.id)
    rows = list(session.scalars(query))
    ids = {r.user_id for r in rows if r.user_id} | {
        i for r in rows if (i := _payload_id(r.payload, "user", "to")) is not None
    }
    people = {u.id: u for u in session.scalars(select(AppUser).where(AppUser.id.in_(ids)))}
    studio_ids = {i for r in rows if (i := _payload_id(r.payload, "studio")) is not None}
    names = dict(
        session.execute(select(Studio.id, Studio.name).where(Studio.id.in_(studio_ids))).all()
    )
    slugs = dict(
        session.execute(
            select(Project.id, Project.slug).where(
                Project.id.in_({r.project_id for r in rows if r.project_id})
            )
        ).all()
    )
    return [
        {
            "id": str(r.id),
            "action": r.action,
            "at": _time(r.created_at),
            "user": user_brief(people[r.user_id]) if r.user_id in people else None,
            "project": slugs.get(r.project_id) if r.project_id else None,
            "subject": user_brief(people[i])
            if (i := _payload_id(r.payload, "user", "to")) in people
            else None,
            "studio": {"id": str(i), "name": names[i]}
            if (i := _payload_id(r.payload, "studio")) in names
            else None,
            "payload": r.payload,
        }
        for r in rows
    ]


def _payload_id(payload: dict[str, Any], *keys: str) -> uuid.UUID | None:
    """The first id under keys in an event payload; None if there is none or it is not an id."""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            try:
                return uuid.UUID(value)
            except ValueError:
                continue
    return None


# --- Changes ---------------------------------------------------------------------------


def set_active(session: Session, admin: AppUser, user: AppUser, active: bool) -> None:
    """Block or unblock a user; blocking ends their sessions. The admin does not block
    themselves."""
    if user.id == admin.id and not active:
        raise AccessError("себя не блокируют")
    user.is_active = active
    if not active:
        end_all_sessions(session, user)
    session.flush()
    audit(
        session,
        "admin_block" if not active else "admin_unblock",
        user=admin,
        payload={"user": str(user.id)},
    )


def end_sessions(session: Session, admin: AppUser, user: AppUser) -> None:
    end_all_sessions(session, user)
    audit(session, "admin_logout", user=admin, payload={"user": str(user.id)})


def _owners(session: Session, studio: Studio) -> int:
    return int(
        session.scalar(
            select(func.count()).where(
                Membership.studio_id == studio.id, Membership.role == "owner"
            )
        )
        or 0
    )


def add_studio_member(
    session: Session, admin: AppUser, studio: Studio, user: AppUser, role: str
) -> None:
    """A person into a firm: owner, designer or installer. One workspace per person; a flat owner
    (client account) is not a firm employee; "Мой ремонт" has only its owner."""
    if role not in STUDIO_ROLES:
        raise AccessError(f"роль в студии — одна из: {', '.join(sorted(STUDIO_ROLES))}")
    if studio.kind != "studio":
        raise AccessError("сотрудники бывают только у фирмы")
    if user.account_type == "client":
        raise AccessError("хозяин квартиры не бывает сотрудником фирмы")
    space = user_space(session, user)
    if space is not None:
        raise AccessError(f"{user.email or user.phone or user.name} уже в «{space.name}»")
    user.account_type = "pro"
    session.add(Membership(studio_id=studio.id, user_id=user.id, role=role))
    session.flush()
    audit(
        session,
        "admin_member_add",
        user=admin,
        payload={"studio": str(studio.id), "user": str(user.id), "role": role},
    )


def _membership(session: Session, studio: Studio, user: AppUser) -> Membership:
    row = session.get(Membership, (studio.id, user.id))
    if row is None:
        raise AccessError("этого человека в студии нет")
    return row


def set_studio_role(
    session: Session, admin: AppUser, studio: Studio, user: AppUser, role: str
) -> None:
    """Change a firm role; the last owner stays an owner."""
    if role not in STUDIO_ROLES:
        raise AccessError(f"роль в студии — одна из: {', '.join(sorted(STUDIO_ROLES))}")
    row = _membership(session, studio, user)
    if studio.kind != "studio" and role != "owner":
        raise AccessError("в «Моём ремонте» только владелец")
    if row.role == "owner" and role != "owner" and _owners(session, studio) <= 1:
        raise AccessError("у студии должен остаться владелец")
    row.role = role
    session.flush()
    audit(
        session,
        "admin_member_role",
        user=admin,
        payload={"studio": str(studio.id), "user": str(user.id), "role": role},
    )


def remove_studio_member(session: Session, admin: AppUser, studio: Studio, user: AppUser) -> None:
    """Take a person out of a firm; the last owner stays."""
    row = _membership(session, studio, user)
    if row.role == "owner" and _owners(session, studio) <= 1:
        raise AccessError("у студии должен остаться владелец")
    session.delete(row)
    session.flush()
    audit(
        session,
        "admin_member_remove",
        user=admin,
        payload={"studio": str(studio.id), "user": str(user.id)},
    )


def add_project_member(
    session: Session, admin: AppUser, project: Project, user: AppUser, role: str
) -> None:
    """A person into one project: client (flat owner, one project) or an outside installer."""
    if role not in PROJECT_ROLES:
        raise AccessError(f"роль в проекте — одна из: {', '.join(sorted(PROJECT_ROLES))}")
    if session.get(ProjectMember, (project.id, user.id)) is not None:
        raise AccessError("этот человек уже в проекте")
    space = user_space(session, user)
    if space is not None and space.id == project.studio_id:
        raise AccessError(f"{user.email or user.phone or user.name} — в студии проекта")
    if role == "client":
        if user.account_type == "pro":
            raise AccessError("клиент — учётка хозяина квартиры, а это студия или монтажник")
        if client_projects(session, user) >= 1:
            raise AccessError("у хозяина квартиры уже есть проект")
        user.account_type = "client"
    elif user.account_type == "client":
        raise AccessError("монтажник — учётка студии, а это хозяин квартиры")
    else:
        user.account_type = "pro"
    session.add(
        ProjectMember(project_id=project.id, user_id=user.id, role=role, invited_by=admin.id)
    )
    session.flush()
    audit(
        session,
        "admin_member_add",
        user=admin,
        project=project,
        payload={"user": str(user.id), "role": role},
    )


def remove_project_member(
    session: Session, admin: AppUser, project: Project, user: AppUser
) -> None:
    row = session.get(ProjectMember, (project.id, user.id))
    if row is None:
        raise AccessError("этого человека в проекте нет")
    session.delete(row)
    session.flush()
    audit(
        session, "admin_member_remove", user=admin, project=project, payload={"user": str(user.id)}
    )


def revoke_invite(session: Session, admin: AppUser, invite: Invite) -> None:
    if invite.accepted_at is not None:
        raise AccessError("приглашение уже принято — уберите человека из участников")
    if invite.revoked_at is None:
        invite.revoked_at = now()
        session.flush()
        project = session.get(Project, invite.project_id) if invite.project_id else None
        audit(
            session,
            "admin_invite_revoke",
            user=admin,
            project=project,
            payload={"invite": str(invite.id)},
        )
