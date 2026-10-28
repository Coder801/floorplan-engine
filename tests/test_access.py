"""Доступ и вход (service/db/access.py) на SQLite в памяти: кто какой проект видит, клиент —
один проект, монтажники независимы, разработчик без доступа к чужим проектам, сессии,
приглашения, поддержка."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db.models import AppUser, Project, ProjectMember, UserSession
from floorplan_engine.service.db.session import create_tables, make_engine, make_sessions


@pytest.fixture
def db() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    create_tables(engine)
    with make_sessions(engine)() as s:
        yield s


def user(db: Session, sub: str, kind: acc.AccountType | None = None) -> AppUser:
    u = acc.oauth_login(db, "google", sub, f"{sub}@example.com", True, sub)
    if kind is not None:
        acc.set_account_type(db, u, kind)
    return u


def role(db: Session, u: AppUser | None, p: Project) -> str | None:
    return acc.project_role(db, acc.Principal(u), p)


def test_pro_sees_own_projects_and_installers_are_independent(db: Session) -> None:
    a, b = user(db, "studio-a", "pro"), user(db, "installer-b", "pro")
    pa = acc.create_project_for(db, a, "Кв 1", "kv1")
    pb = acc.create_project_for(db, b, "Кв 2", "kv2")
    acc.create_project_for(db, b, "Кв 3", "kv3")  # у pro проектов сколько угодно
    assert role(db, a, pa) == "owner" and role(db, a, pb) is None
    assert acc.visible_slugs(db, acc.Principal(b), {"kv1", "kv2", "kv3"}) == {"kv2", "kv3"}


def test_client_has_one_project_and_sees_everything_in_it(db: Session) -> None:
    c = user(db, "owner-flat", "client")
    p = acc.create_project_for(db, c, "Моя квартира", "flat")
    assert role(db, c, p) == "owner"  # своё пространство — владелец
    assert acc.can(role(db, c, p), "view")
    with pytest.raises(acc.AccessError, match="один проект"):
        acc.create_project_for(db, c, "Вторая", "flat2")


def test_invited_client_and_one_client_project_in_db(db: Session) -> None:
    studio = user(db, "studio", "pro")
    p1 = acc.create_project_for(db, studio, "Кв 1", "kv1")
    p2 = acc.create_project_for(db, studio, "Кв 2", "kv2")
    c = user(db, "client")  # тип выберет приглашение
    acc.accept_invite(db, c, acc.create_invite(db, studio, "client", project=p1))
    assert c.account_type == "client" and role(db, c, p1) == "client"
    assert acc.can("client", "answer") and not acc.can("client", "edit_wiring")
    with pytest.raises(acc.AccessError, match="уже есть проект"):
        acc.accept_invite(db, c, acc.create_invite(db, studio, "client", project=p2))
    # И база не даст: частичный уникальный индекс
    db.add(ProjectMember(project_id=p2.id, user_id=c.id, role="client"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_outside_installer_sees_only_invited_project(db: Session) -> None:
    studio = user(db, "studio", "pro")
    p1 = acc.create_project_for(db, studio, "Кв 1", "kv1")
    p2 = acc.create_project_for(db, studio, "Кв 2", "kv2")
    inst = user(db, "installer", "pro")
    acc.accept_invite(db, inst, acc.create_invite(db, studio, "installer", project=p1))
    assert role(db, inst, p1) == "installer" and role(db, inst, p2) is None
    assert acc.can("installer", "edit_wiring")


def test_client_invites_only_installer(db: Session) -> None:
    c = user(db, "flat-owner", "client")
    p = acc.create_project_for(db, c, "Квартира", "flat")
    acc.create_invite(db, c, "installer", project=p)
    with pytest.raises(acc.AccessError, match="только монтажника"):
        acc.create_invite(db, c, "client", project=p)


def test_developer_needs_support_grant(db: Session) -> None:
    studio = user(db, "studio", "pro")
    p = acc.create_project_for(db, studio, "Кв 1", "kv1")
    dev = user(db, "developer", "pro")  # обычный pro со своей тестовой студией
    assert role(db, dev, p) is None
    grant = acc.grant_support(db, p, dev, studio, "не рисуется щит")
    assert role(db, dev, p) == "support" and acc.can("support", "edit_wiring")
    grant.expires_at = acc.now() - timedelta(minutes=1)
    assert role(db, dev, p) is None  # срок вышел
    acc.grant_support(db, p, dev, studio, "ещё раз")
    acc.revoke_support(db, p, dev)
    assert role(db, dev, p) is None
    with pytest.raises(acc.AccessError, match="владелец"):
        acc.grant_support(db, p, dev, dev, "сам себе")


def test_superuser_and_visitor(db: Session) -> None:
    studio = user(db, "studio", "pro")
    p = acc.create_project_for(db, studio, "Кв 1", "kv1")
    boss = acc.oauth_login(
        db, "google", "boss", "Boss@Example.com", True, superusers=["boss@example.com"]
    )
    assert role(db, boss, p) == "superuser"
    assert role(db, None, p) == "visitor"
    assert acc.can("visitor", "view") and not acc.can("visitor", "edit_wiring")
    assert acc.visible_slugs(db, acc.VISITOR, {"kv1", "folder-only"}) == {"kv1", "folder-only"}
    boss.is_active = False
    assert role(db, boss, p) is None


def test_oauth_links_only_verified_email(db: Session) -> None:
    a = acc.oauth_login(db, "google", "g1", "same@example.com", True, "А")
    again = acc.oauth_login(db, "google", "g1", "same@example.com", True)
    assert again.id == a.id
    linked = acc.oauth_login(db, "other", "x1", "SAME@example.com", True)
    assert linked.id == a.id  # подтверждённый email — тот же пользователь
    stranger = acc.oauth_login(db, "other", "x2", "same@example.com", False)
    assert stranger.id != a.id and stranger.email is None  # неподтверждённый — новый


def test_sessions_expire_and_end(db: Session) -> None:
    u = user(db, "u", "pro")
    token = acc.create_session(db, u, "pytest")
    assert acc.session_user(db, token) is u
    assert acc.session_user(db, "чужой") is None
    row = db.query(UserSession).one()
    assert row.token_hash != token  # в базе только хеш
    row.expires_at = acc.now() - timedelta(seconds=1)
    assert acc.session_user(db, token) is None
    t2 = acc.create_session(db, u)
    acc.end_session(db, t2)
    assert acc.session_user(db, t2) is None


def test_invite_expires_and_is_single_use(db: Session) -> None:
    studio = user(db, "studio", "pro")
    p = acc.create_project_for(db, studio, "Кв 1", "kv1")
    token = acc.create_invite(db, studio, "installer", project=p, days=0)
    with pytest.raises(acc.AccessError, match="срок"):
        acc.accept_invite(db, user(db, "late", "pro"), token)
    token = acc.create_invite(db, studio, "installer", project=p)
    acc.accept_invite(db, user(db, "first", "pro"), token)
    with pytest.raises(acc.AccessError, match="уже принято"):
        acc.accept_invite(db, user(db, "second", "pro"), token)
    with pytest.raises(acc.AccessError, match="нет права"):
        acc.create_invite(db, user(db, "nobody", "pro"), "installer", project=p)


def test_studio_invite_makes_member(db: Session) -> None:
    owner = user(db, "owner", "pro")
    studio = acc.own_studio(db, owner)
    assert studio is not None
    p = acc.create_project_for(db, owner, "Кв 1", "kv1")
    designer = user(db, "designer")
    acc.accept_invite(db, designer, acc.create_invite(db, owner, "designer", studio=studio))
    assert designer.account_type == "pro" and role(db, designer, p) == "designer"
    with pytest.raises(acc.AccessError, match="тип учётной записи уже выбран"):
        acc.set_account_type(db, designer, "client")
