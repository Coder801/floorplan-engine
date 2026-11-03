"""Код доступа к проекту (service/db/access_codes.py): выдача, вход, срок, отзыв, роль viewer."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import access_codes as codes
from floorplan_engine.service.db.models import AppUser, AuditEvent


def _user(db: Session, name: str, kind: acc.AccountType) -> AppUser:
    u = acc.oauth_login(db, "google", name, f"{name}@example.com", True, name)
    acc.set_account_type(db, u, kind)
    return u


def test_code_format_and_normalize() -> None:
    assert codes.format_code("ABCD2345") == "ABCD-2345"
    assert codes.normalize_code(" abcd-2345 ") == "ABCD2345"
    for bad in ("ABCD-234", "ABCD-2340", "ABCD-234O", "", "abcdefghj"):
        with pytest.raises(acc.AccessError, match="не подходит"):
            codes.normalize_code(bad)


def test_issue_use_and_viewer_role(db: Session) -> None:
    studio = _user(db, "studio", "pro")
    kv1 = acc.create_project_for(db, studio, "Кв 1", "kv1")
    kv2 = acc.create_project_for(db, studio, "Кв 2", "kv2")
    code = codes.issue_code(db, kv1, studio, label="Иван")
    assert len(code) == 9 and code[4] == "-" and code.upper() == code

    row = codes.use_code(db, code.lower().replace("-", " "))  # как ни введи
    assert row.project_id == kv1.id and row.uses == 1 and row.label == "Иван"
    who = acc.Principal(None, code_project=row.project_id)
    assert who.by_code and not who.visitor
    assert acc.project_role(db, who, kv1) == "viewer"
    assert acc.project_role(db, who, kv2) is None
    assert acc.project_role(db, who, None) is None
    assert acc.can("viewer", "view") and not acc.can("viewer", "edit_wiring")
    assert not acc.can("viewer", "answer") and not acc.can("viewer", "choose_variant")
    assert acc.visible_slugs(db, who, {"kv1", "kv2", "other"}) == {"kv1"}
    assert codes.active_code(db, row.id) is row
    assert codes.use_code(db, code).uses == 2  # входов сколько угодно


def test_wrong_code_same_message(db: Session) -> None:
    with pytest.raises(acc.AccessError, match=codes.BAD_CODE):
        codes.use_code(db, "ABCD-2345")


def test_code_expires_and_is_revoked(db: Session) -> None:
    studio = _user(db, "studio", "pro")
    kv1 = acc.create_project_for(db, studio, "Кв 1", "kv1")
    code = codes.issue_code(db, kv1, None, days=3)
    row = codes.use_code(db, code)
    row.expires_at = acc.now() - timedelta(seconds=1)
    db.flush()
    assert codes.active_code(db, row.id) is None
    with pytest.raises(acc.AccessError, match=codes.BAD_CODE):
        codes.use_code(db, code)

    fresh = codes.issue_code(db, kv1, None, label="соседка")
    rows = codes.list_codes(db, kv1)
    assert [r.label for r in rows] == ["соседка", ""]
    revoked = codes.revoke_code(db, kv1, str(rows[0].id)[:8])
    assert revoked.revoked_at is not None
    assert codes.active_code(db, revoked.id) is None
    with pytest.raises(acc.AccessError, match=codes.BAD_CODE):
        codes.use_code(db, fresh)
    with pytest.raises(acc.AccessError, match="нет"):
        codes.revoke_code(db, kv1, "nope")


def test_issue_needs_invite_right(db: Session) -> None:
    studio = _user(db, "studio", "pro")
    other = _user(db, "other", "pro")
    kv1 = acc.create_project_for(db, studio, "Кв 1", "kv1")
    with pytest.raises(acc.AccessError, match="нет права"):
        codes.issue_code(db, kv1, other)
    with pytest.raises(acc.AccessError, match="Срок"):
        codes.issue_code(db, kv1, studio, days=0)


def test_ensure_fixed_code(db: Session) -> None:
    """Постоянный код (SHTROBA_ACCESS_CODES): записывается с известным значением, повтор не
    дублирует, отозванный оживает, тот же код у другого проекта — ошибка."""
    studio = _user(db, "studio", "pro")
    kv1 = acc.create_project_for(db, studio, "Кв 1", "kv1")
    kv2 = acc.create_project_for(db, studio, "Кв 2", "kv2")
    row = codes.ensure_code(db, kv1, "abcd-2345")
    assert codes.use_code(db, "ABCD-2345").id == row.id
    assert row.expires_at.date() > (acc.now() + timedelta(days=365)).date()

    def fixes() -> int:
        return db.query(AuditEvent).filter_by(action="code_fix").count()

    assert fixes() == 1
    assert codes.ensure_code(db, kv1, "ABCD2345").id == row.id
    assert len(codes.list_codes(db, kv1)) == 1 and fixes() == 1  # действующий код — без записей
    codes.revoke_code(db, kv1, str(row.id))
    with pytest.raises(acc.AccessError, match="не подходит"):
        codes.use_code(db, "ABCD-2345")
    assert codes.ensure_code(db, kv1, "ABCD-2345").revoked_at is None and fixes() == 2
    assert codes.use_code(db, "ABCD-2345").id == row.id
    with pytest.raises(acc.AccessError, match="другому проекту"):
        codes.ensure_code(db, kv2, "ABCD-2345")
    with pytest.raises(acc.AccessError, match="не подходит"):
        codes.ensure_code(db, kv2, "ABCD-234")
