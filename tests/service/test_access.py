"""Access and login (service/db/access.py) on in-memory SQLite: who sees which project, a client
has one project, installers are independent, a developer has no access to other people's
projects, sessions, invites, support."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db.models import (
    AppUser,
    Membership,
    Project,
    ProjectMember,
    UserSession,
)


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
    acc.create_project_for(db, b, "Кв 3", "kv3")  # pro can have any number of projects
    assert role(db, a, pa) == "owner" and role(db, a, pb) is None
    assert acc.visible_slugs(db, acc.Principal(b), {"kv1", "kv2", "kv3"}) == {"kv2", "kv3"}


def test_client_has_one_project_and_sees_everything_in_it(db: Session) -> None:
    c = user(db, "owner-flat", "client")
    p = acc.create_project_for(db, c, "Моя квартира", "flat")
    assert role(db, c, p) == "owner"  # own workspace: owner
    assert acc.can(role(db, c, p), "view")
    with pytest.raises(acc.AccessError, match="один проект"):
        acc.create_project_for(db, c, "Вторая", "flat2")


def test_invited_client_and_one_client_project_in_db(db: Session) -> None:
    studio = user(db, "studio", "pro")
    p1 = acc.create_project_for(db, studio, "Кв 1", "kv1")
    p2 = acc.create_project_for(db, studio, "Кв 2", "kv2")
    c = user(db, "client")  # the invite will choose the type
    acc.accept_invite(db, c, acc.create_invite(db, studio, "client", project=p1))
    assert c.account_type == "client" and role(db, c, p1) == "client"
    assert acc.can("client", "answer") and not acc.can("client", "edit_wiring")
    with pytest.raises(acc.AccessError, match="уже есть проект"):
        acc.accept_invite(db, c, acc.create_invite(db, studio, "client", project=p2))
    # The database will not allow it either: partial unique index
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
    dev = user(db, "developer", "pro")  # a regular pro with their own test studio
    assert role(db, dev, p) is None
    grant = acc.grant_support(db, p, dev, studio, "не рисуется щит")
    assert role(db, dev, p) == "support" and acc.can("support", "edit_wiring")
    grant.expires_at = acc.now() - timedelta(minutes=1)
    assert role(db, dev, p) is None  # expired
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
    assert linked.id == a.id  # a confirmed e-mail is the same user
    stranger = acc.oauth_login(db, "other", "x2", "same@example.com", False)
    assert stranger.id != a.id and stranger.email is None  # an unconfirmed one is new


def test_sessions_expire_and_end(db: Session) -> None:
    u = user(db, "u", "pro")
    token = acc.create_session(db, u, "pytest")
    assert acc.session_user(db, token) is u
    assert acc.session_user(db, "чужой") is None
    row = db.query(UserSession).one()
    assert row.token_hash != token  # only the hash is stored
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


def test_register_firm(db: Session) -> None:
    """A firm has a name and a kind; one per person; a firm employee does not create their own."""
    owner = user(db, "owner")
    with pytest.raises(acc.AccessError, match="чем занимается"):
        acc.register_firm(db, owner, "Искра", "bakery")
    with pytest.raises(acc.AccessError, match="Телефон"):
        acc.register_firm(db, owner, "Искра", "electric", phone="звоните")
    firm = acc.register_firm(db, owner, " Искра ", "electric", " Киев ", "+380 (44) 123-45")
    assert (firm.kind, firm.name, firm.business, firm.city) == (
        "studio",
        "Искра",
        "electric",
        "Киев",
    )
    assert owner.account_type == "pro" and acc.user_space(db, owner) is firm
    with pytest.raises(acc.AccessError, match="уже"):
        acc.register_firm(db, owner, "Вторая", "design")
    staff = user(db, "staff")
    acc.accept_invite(db, staff, acc.create_invite(db, owner, "installer", studio=firm))
    assert acc.user_space(db, staff) is firm
    with pytest.raises(acc.AccessError, match="уже"):
        acc.register_firm(db, staff, "Своя", "master")
    personal = user(db, "flat", "client")
    space = acc.user_space(db, personal)
    assert space is not None and space.kind == "personal" and space.business is None


def test_adopt_folders_links_new_slugs_once(db: Session) -> None:
    """Owner login: folders without a row go to them; again, nothing; other rows are not touched."""
    linked, reason = acc.adopt_folders(db, "owner@example.com", ["kv1", "kv2"])
    assert linked == [] and reason is not None and "owner@example.com" in reason  # never logged in
    u = user(db, "owner")
    linked, reason = acc.adopt_folders(db, "owner@example.com", ["kv1"])
    assert linked == [] and "тип" in (reason or "")  # account type not chosen
    acc.set_account_type(db, u, "pro")
    other = user(db, "other", "pro")
    acc.create_project_for(db, other, "Чужой", "kv2")
    linked, reason = acc.adopt_folders(db, "Owner@Example.com", ["kv2", "kv1", "kv3"])
    assert (linked, reason) == (["kv1", "kv3"], None)
    kv1, kv2 = acc.project_by_slug(db, "kv1"), acc.project_by_slug(db, "kv2")
    assert kv1 is not None and kv2 is not None
    assert role(db, u, kv1) == "owner"
    assert role(db, u, kv2) is None  # stayed with other
    assert acc.adopt_folders(db, "owner@example.com", ["kv1", "kv2", "kv3"]) == ([], None)


def test_adopt_folders_takes_unowned_projects(db: Session) -> None:
    """A project written from the command line without an owner (an access code before login) moves
    into the owner's studio when they log in; other people's and already owned ones are not
    touched."""
    kv1 = acc.create_project_unowned(db, "kv1", "kv1")
    assert acc.unowned_studio(db).id == kv1.studio_id
    with pytest.raises(acc.AccessError, match="уже в базе"):
        acc.create_project_unowned(db, "kv1", "kv1")
    u = user(db, "owner", "pro")
    assert role(db, u, kv1) is None
    linked, reason = acc.adopt_folders(db, "owner@example.com", ["kv1", "kv2"])
    assert (linked, reason) == (["kv2", "kv1"], None)
    assert role(db, u, kv1) == "owner"
    assert acc.adopt_folders(db, "owner@example.com", ["kv1", "kv2"]) == ([], None)


def test_adopt_folders_client_gets_one_project(db: Session) -> None:
    user(db, "home", "client")
    linked, reason = acc.adopt_folders(db, "home@example.com", ["b", "a"])
    assert linked == ["a"] and reason is not None  # a flat owner cannot have a second project


def test_personal_owner_chooses_variant_studio_client_does_not(db: Session) -> None:
    """In "Мой ремонт" the owner of their own workspace chooses the variant and edits routes; a
    studio client only views (docs/wiring-variants.md)."""
    home = user(db, "home", "client")
    own = acc.create_project_for(db, home, "Моя квартира", "home")
    assert acc.can(role(db, home, own), "choose_variant")
    assert acc.can(role(db, home, own), "edit_wiring")
    studio = user(db, "studio", "pro")
    flat = acc.create_project_for(db, studio, "Кв", "kv")
    guest = user(db, "guest")
    acc.accept_invite(db, guest, acc.create_invite(db, studio, "client", project=flat))
    assert role(db, guest, flat) == "client"
    assert not acc.can("client", "choose_variant") and not acc.can("client", "edit_wiring")


def test_studios_do_not_cross(db: Session) -> None:
    """Two firms with every role: each person sees exactly their projects — the one query
    visible_projects agrees with project_role, nothing of the other studio leaks, and no one can
    invite into or open support for a project of the other studio."""
    people: dict[str, AppUser] = {}
    projects: dict[str, Project] = {}
    for firm in ("a", "b"):
        owner = people[f"{firm}-owner"] = user(db, f"{firm}-owner", "pro")
        studio = acc.own_studio(db, owner)
        assert studio is not None
        for n in (1, 2):
            projects[f"{firm}{n}"] = acc.create_project_for(db, owner, f"{firm}{n}", f"{firm}{n}")
        for staff in ("designer", "installer"):
            p = people[f"{firm}-{staff}"] = user(db, f"{firm}-{staff}")
            acc.accept_invite(db, p, acc.create_invite(db, owner, staff, studio=studio))
        client = people[f"{firm}-client"] = user(db, f"{firm}-client")
        acc.accept_invite(
            db, client, acc.create_invite(db, owner, "client", project=projects[f"{firm}1"])
        )
        outside = people[f"{firm}-outside"] = user(db, f"{firm}-outside")
        acc.accept_invite(
            db, outside, acc.create_invite(db, owner, "installer", project=projects[f"{firm}2"])
        )
    expected = {
        "owner": {"1", "2"},
        "designer": {"1", "2"},
        "installer": {"1", "2"},
        "client": {"1"},
        "outside": {"2"},
    }
    for name, person in people.items():
        firm, kind = name.split("-")
        want = {firm + n for n in expected[kind]}
        who = acc.Principal(person)
        assert {p.slug for p in db.scalars(acc.visible_projects(db, who))} == want, name
        assert {s for s, p in projects.items() if role(db, person, p) is not None} == want, name
        assert acc.visible_slugs(db, who, set(projects)) == want, name
    other = projects["b1"]
    for name in ("a-owner", "a-designer"):
        with pytest.raises(acc.AccessError, match="нет права"):
            acc.create_invite(db, people[name], "installer", project=other)
    with pytest.raises(acc.AccessError, match="владелец"):
        acc.grant_support(db, other, people["a-designer"], people["a-owner"], "чужой проект")


def test_one_workspace_per_person(db: Session) -> None:
    """A firm employee is not taken into a second firm, nor is an owner; the database
    keeps it too."""
    a, b = user(db, "a", "pro"), user(db, "b", "pro")
    firm_a, firm_b = acc.own_studio(db, a), acc.own_studio(db, b)
    assert firm_a is not None and firm_b is not None
    staff = user(db, "staff")
    acc.accept_invite(db, staff, acc.create_invite(db, a, "installer", studio=firm_a))
    with pytest.raises(acc.AccessError, match="в другую фирму нельзя"):
        acc.accept_invite(db, staff, acc.create_invite(db, b, "installer", studio=firm_b))
    with pytest.raises(acc.AccessError, match="в другую фирму нельзя"):
        acc.accept_invite(db, a, acc.create_invite(db, b, "designer", studio=firm_b))
    acc.accept_invite(
        db, staff, acc.create_invite(db, a, "designer", studio=firm_a)
    )  # same firm: no-op
    assert acc.user_space(db, staff) is firm_a
    db.add(Membership(studio_id=firm_b.id, user_id=staff.id, role="installer"))
    with pytest.raises(IntegrityError):
        db.flush()
