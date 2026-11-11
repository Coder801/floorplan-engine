"""Project access code (decision 2026-11-02, docs/database.md, "Login"): the studio issues a code
(`floorplan-engine access code projects/<name>`), a person enters it on the login screen and
opens that one project, without an account (access.project_role). The code has a role: `viewer`
only views, `client_code` (decision 2026-11-11) also answers questions and sets the project up in
the wizard — for a studio client who has no account.

A code is CODE_LENGTH characters from CODE_ALPHABET (no 0/O and 1/I, so they are not confused
by ear or in chat), shown as "XXXX-XXXX"; it is valid for CODE_DAYS, can be used any number of
times and can be revoked by the studio. The database (`access_code`) stores only the sha256 of
the code. Functions do not commit, like access.py.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from floorplan_engine.service.db.access import (
    CODE_ROLES,
    AccessError,
    CodeRole,
    Principal,
    audit,
    aware,
    can,
    now,
    project_role,
    token_hash,
)
from floorplan_engine.service.db.models import AccessCode, AppUser, Project

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_DAYS = 30
FIXED_DAYS = 3650  # permanent code from the environment (ensure_code), extended on every start
BAD_CODE = "Код не подходит или срок его истёк"


def normalize_code(value: str) -> str:
    """Code as stored: no spaces or dashes, upper case; AccessError if it does not look like a
    code.
    """
    code = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    if len(code) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in code):
        raise AccessError(BAD_CODE)
    return code


def format_code(code: str) -> str:
    """Code for a human: "XXXX-XXXX"."""
    half = CODE_LENGTH // 2
    return f"{code[:half]}-{code[half:]}"


def _hash(code: str) -> str:
    return token_hash(f"access-code:{code}")


def issue_code(
    session: Session,
    project: Project,
    by: AppUser | None = None,
    label: str = "",
    days: int = CODE_DAYS,
    role: str = "viewer",
) -> str:
    """New project access code; by is who issues it (None means a superuser from the command line),
    the invite permission is required; role is viewer or client_code. Returns the code as
    "XXXX-XXXX", to be shown once."""
    if (
        by is not None
        and not by.is_superuser
        and not can(project_role(session, Principal(by), project), "invite")
    ):
        raise AccessError("нет права выдавать код доступа")
    if role not in CODE_ROLES:
        raise AccessError("Вид кода — просмотр (viewer) или заказчик (client_code)")
    label = label.strip()
    if len(label) > 200:
        raise AccessError("Подпись кода — не длиннее 200 символов")
    if not 1 <= days <= 365:
        raise AccessError("Срок кода — от 1 до 365 дней")
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    session.add(
        AccessCode(
            project_id=project.id,
            code_hash=_hash(code),
            label=label,
            role=role,
            created_by=by.id if by else None,
            expires_at=now() + timedelta(days=days),
        )
    )
    session.flush()
    audit(session, "code_issue", user=by, project=project, payload={"label": label, "role": role})
    return format_code(code)


def ensure_code(
    session: Session, project: Project, value: str, label: str = "постоянный код"
) -> AccessCode:
    """Permanent access code with a known value (SHTROBA_ACCESS_CODES, set by the service on start):
    missing in the database means write it, revoked means bring it back (clear the revocation,
    extend by FIXED_DAYS): the environment variable is the source of truth, so revoking such a
    code lasts until restart. The same code on another project is an AccessError. A valid code
    means nothing is written or logged: a restart does not pile up records."""
    wanted = _hash(normalize_code(value))
    row = session.scalar(select(AccessCode).where(AccessCode.code_hash == wanted))
    if row is not None and row.project_id != project.id:
        raise AccessError(f"код уже выдан другому проекту (не {project.slug})")
    if row is not None and _alive(row):
        return row
    expires = now() + timedelta(days=FIXED_DAYS)
    if row is None:
        row = AccessCode(
            project_id=project.id, code_hash=wanted, label=label.strip()[:200], expires_at=expires
        )
        session.add(row)
    else:
        row.revoked_at = None
        row.expires_at = expires
    session.flush()
    audit(session, "code_fix", project=project, payload={"code": str(row.id)})
    return row


def use_code(session: Session, value: str) -> AccessCode:
    """Login by code: a valid code bumps the login counter and the log and returns the code row (the
    project is project_id). Unknown, revoked or expired gives AccessError with one and the same
    message: someone else's code is not revealed."""
    wanted = _hash(normalize_code(value))
    row = session.scalar(select(AccessCode).where(AccessCode.code_hash == wanted))
    if row is None or not _alive(row):
        raise AccessError(BAD_CODE)
    row.uses += 1
    row.last_used_at = now()
    session.flush()
    project = session.get(Project, row.project_id)
    audit(session, "code_login", project=project, payload={"code": str(row.id)})
    return row


def active_code(session: Session, code_id: uuid.UUID) -> AccessCode | None:
    """Code by id, for checking every request: None if revoked, expired or deleted."""
    row = session.get(AccessCode, code_id)
    return row if row is not None and _alive(row) else None


def _alive(row: AccessCode) -> bool:
    return row.revoked_at is None and aware(row.expires_at) > now()


def list_codes(session: Session, project: Project) -> list[AccessCode]:
    return list(
        session.scalars(
            select(AccessCode)
            .where(AccessCode.project_id == project.id)
            .order_by(AccessCode.created_at.desc())
        )
    )


def revoke_code(
    session: Session, project: Project, code_id: str, by: AppUser | None = None
) -> AccessCode:
    """Revoke a code by id (a prefix of the id works if it is unique); logins with it stop from the
    next request."""
    rows = [
        r for r in list_codes(session, project) if str(r.id).startswith(code_id.strip().lower())
    ]
    if not rows:
        raise AccessError(f"кода {code_id} у проекта нет")
    if len(rows) > 1:
        raise AccessError(f"кодов, начинающихся на {code_id}, несколько — укажите длиннее")
    row = rows[0]
    if row.revoked_at is None:
        row.revoked_at = now()
        session.flush()
        audit(session, "code_revoke", user=by, project=project, payload={"code": str(row.id)})
    return row


def code_role(row: AccessCode) -> CodeRole:
    """The code's role; anything unknown (a row written by hand) only views."""
    return "client_code" if row.role == "client_code" else "viewer"
