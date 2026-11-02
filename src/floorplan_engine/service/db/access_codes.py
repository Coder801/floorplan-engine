"""Код доступа к проекту (решение 2026-11-02, docs/database.md, «Вход»): студия выдаёт код
(`floorplan-engine access code projects/<имя>`), человек вводит его на экране входа и видит этот
один проект — без учётки, только чтение (роль `viewer`, access.project_role).

Код — CODE_LENGTH знаков из CODE_ALPHABET (без 0/O и 1/I, чтобы не путать на слух и в
переписке), показывается как «XXXX-XXXX»; действует CODE_DAYS, входов по нему сколько угодно,
отзывается студией. В базе (`access_code`) — только sha256 кода. Функции не делают commit, как
access.py.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from floorplan_engine.service.db.access import (
    AccessError,
    Principal,
    _aware,
    audit,
    can,
    now,
    project_role,
    token_hash,
)
from floorplan_engine.service.db.models import AccessCode, AppUser, Project

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_DAYS = 30
BAD_CODE = "Код не подходит или срок его истёк"


def normalize_code(value: str) -> str:
    """Код как в базе: без пробелов и дефисов, заглавными; не похож на код — AccessError."""
    code = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    if len(code) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in code):
        raise AccessError(BAD_CODE)
    return code


def format_code(code: str) -> str:
    """Код для человека: «XXXX-XXXX»."""
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
) -> str:
    """Новый код доступа к проекту; by — кто выдаёт (None — суперпользователь из командной
    строки), нужно право приглашать. Вернёт код в виде «XXXX-XXXX» — показать один раз."""
    if (
        by is not None
        and not by.is_superuser
        and not can(project_role(session, Principal(by), project), "invite")
    ):
        raise AccessError("нет права выдавать код доступа")
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
            created_by=by.id if by else None,
            expires_at=now() + timedelta(days=days),
        )
    )
    session.flush()
    audit(session, "code_issue", user=by, project=project, payload={"label": label})
    return format_code(code)


def use_code(session: Session, value: str) -> AccessCode:
    """Вход по коду: действующий код — счётчик входов и журнал, вернёт строку кода (проект —
    project_id). Нет такого, отозван или истёк — AccessError с одним и тем же сообщением:
    чужой код не раскрывается."""
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
    """Код по id для проверки каждого запроса: отозван, истёк или удалён — None."""
    row = session.get(AccessCode, code_id)
    return row if row is not None and _alive(row) else None


def _alive(row: AccessCode) -> bool:
    return row.revoked_at is None and _aware(row.expires_at) > now()


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
    """Отозвать код по id (можно по началу id, если он один такой); входы по нему кончаются
    со следующего запроса."""
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
