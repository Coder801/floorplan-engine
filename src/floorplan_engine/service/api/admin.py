"""Platform admin API /api/admin/* (decision 2026-11-03, docs/database.md, "Admin"): CRUD over
studios, users, projects, members, invites, access codes and support for the superuser. The
admin page is its own front (admin/). Access: Auth.check lets only an active superuser in (the
rest get 403); rules and views live in db/admin.py.

Errors: a broken rule (AccessError) gives 409 with the reason, an unknown id gives 404.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import access_codes
from floorplan_engine.service.db import admin as adm
from floorplan_engine.service.db.models import AppUser, Invite, Project, Studio

if TYPE_CHECKING:
    from floorplan_engine.service.api.auth import Auth

PREFIX = "/api/admin"
T = TypeVar("T")


class MemberIn(BaseModel):
    user: str
    role: str


class RoleIn(BaseModel):
    role: str


class InviteIn(BaseModel):
    role: str
    email: str | None = None
    days: int = Field(default=acc.INVITE_DAYS, ge=1, le=60)


class CodeIn(BaseModel):
    label: str = ""
    role: str = "viewer"  # viewer or client_code (access_codes.issue_code)
    days: int = Field(default=access_codes.CODE_DAYS, ge=1, le=365)


class SupportIn(BaseModel):
    user: str
    reason: str = Field(min_length=1, max_length=500)
    hours: int = Field(default=acc.SUPPORT_HOURS, ge=1, le=24 * 30)


class ActiveIn(BaseModel):
    active: bool


class _Call(Protocol):
    """A function in the admin's transaction (admin_router.call)."""

    def __call__(self, request: Request, fn: Callable[[Session, AppUser], T]) -> T: ...


def _view_routes(r: APIRouter, call: _Call) -> None:
    """Read-only views."""

    # --- views ---------------------------------------------------------------------------

    @r.get("/summary")
    def summary(request: Request) -> dict[str, int]:
        return call(request, lambda db, _: adm.summary(db))

    @r.get("/studios")
    def studios(request: Request) -> list[dict[str, Any]]:
        return call(request, lambda db, _: adm.studios(db))

    @r.get("/studios/{studio_id}")
    def studio(request: Request, studio_id: str) -> dict[str, Any]:
        return call(request, lambda db, _: adm.studio_detail(db, adm.get(db, Studio, studio_id)))

    @r.get("/users")
    def users(request: Request, q: str = "") -> list[dict[str, Any]]:
        return call(request, lambda db, _: adm.users(db, q))

    @r.get("/users/{user_id}")
    def user(request: Request, user_id: str) -> dict[str, Any]:
        return call(request, lambda db, _: adm.user_detail(db, adm.get(db, AppUser, user_id)))

    @r.get("/projects")
    def projects(request: Request) -> list[dict[str, Any]]:
        return call(request, lambda db, _: adm.projects(db))

    @r.get("/projects/{project_id}")
    def project(request: Request, project_id: str) -> dict[str, Any]:
        return call(request, lambda db, _: adm.project_detail(db, adm.get(db, Project, project_id)))

    @r.get("/events")
    def events(
        request: Request, project: str | None = None, user: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        return call(
            request,
            lambda db, _: adm.events(
                db,
                adm.get(db, Project, project) if project else None,
                adm.get(db, AppUser, user) if user else None,
                limit,
            ),
        )


def _user_routes(r: APIRouter, call: _Call) -> None:
    """Users."""

    # --- users ---------------------------------------------------------------------------

    @r.post("/users/{user_id}/active")
    def set_active(request: Request, user_id: str, body: ActiveIn) -> dict[str, Any]:
        def run(db: Session, admin: AppUser) -> dict[str, Any]:
            target = adm.get(db, AppUser, user_id)
            adm.set_active(db, admin, target, body.active)
            return adm.user_detail(db, target)

        return call(request, run)

    @r.post("/users/{user_id}/logout")
    def logout(request: Request, user_id: str) -> dict[str, Any]:
        def run(db: Session, admin: AppUser) -> dict[str, Any]:
            target = adm.get(db, AppUser, user_id)
            adm.end_sessions(db, admin, target)
            return adm.user_detail(db, target)

        return call(request, run)


def _studio_routes(r: APIRouter, call: _Call, invite_url: Callable[[str], str]) -> None:
    """Studio members and invites."""

    # --- studio members and invites --------------------------------------------------------

    @r.post("/studios/{studio_id}/members")
    def add_studio_member(request: Request, studio_id: str, body: MemberIn) -> dict[str, Any]:
        def run(db: Session, admin: AppUser) -> dict[str, Any]:
            studio = adm.get(db, Studio, studio_id)
            adm.add_studio_member(db, admin, studio, adm.get(db, AppUser, body.user), body.role)
            return adm.studio_detail(db, studio)

        return call(request, run)

    @r.patch("/studios/{studio_id}/members/{user_id}")
    def set_studio_role(
        request: Request, studio_id: str, user_id: str, body: RoleIn
    ) -> dict[str, Any]:
        def run(db: Session, admin: AppUser) -> dict[str, Any]:
            studio = adm.get(db, Studio, studio_id)
            adm.set_studio_role(db, admin, studio, adm.get(db, AppUser, user_id), body.role)
            return adm.studio_detail(db, studio)

        return call(request, run)

    @r.delete("/studios/{studio_id}/members/{user_id}")
    def remove_studio_member(request: Request, studio_id: str, user_id: str) -> dict[str, Any]:
        def run(db: Session, admin: AppUser) -> dict[str, Any]:
            studio = adm.get(db, Studio, studio_id)
            adm.remove_studio_member(db, admin, studio, adm.get(db, AppUser, user_id))
            return adm.studio_detail(db, studio)

        return call(request, run)

    @r.post("/studios/{studio_id}/invites")
    def studio_invite(request: Request, studio_id: str, body: InviteIn) -> dict[str, str]:
        def run(db: Session, admin: AppUser) -> dict[str, str]:
            studio = adm.get(db, Studio, studio_id)
            token = acc.create_invite(
                db, admin, body.role, studio=studio, email=body.email, days=body.days
            )
            return {"url": invite_url(token)}

        return call(request, run)


def _project_routes(r: APIRouter, call: _Call, invite_url: Callable[[str], str]) -> None:
    """Project members, invites, access codes and support access."""

    # --- project members, invites, codes, support -----------------------------------------

    @r.post("/projects/{project_id}/members")
    def add_project_member(request: Request, project_id: str, body: MemberIn) -> dict[str, Any]:
        def run(db: Session, admin: AppUser) -> dict[str, Any]:
            project = adm.get(db, Project, project_id)
            adm.add_project_member(db, admin, project, adm.get(db, AppUser, body.user), body.role)
            return adm.project_detail(db, project)

        return call(request, run)

    @r.delete("/projects/{project_id}/members/{user_id}")
    def remove_project_member(request: Request, project_id: str, user_id: str) -> dict[str, Any]:
        def run(db: Session, admin: AppUser) -> dict[str, Any]:
            project = adm.get(db, Project, project_id)
            adm.remove_project_member(db, admin, project, adm.get(db, AppUser, user_id))
            return adm.project_detail(db, project)

        return call(request, run)

    @r.post("/projects/{project_id}/invites")
    def project_invite(request: Request, project_id: str, body: InviteIn) -> dict[str, str]:
        def run(db: Session, admin: AppUser) -> dict[str, str]:
            project = adm.get(db, Project, project_id)
            token = acc.create_invite(
                db, admin, body.role, project=project, email=body.email, days=body.days
            )
            return {"url": invite_url(token)}

        return call(request, run)

    @r.delete("/invites/{invite_id}")
    def revoke_invite(request: Request, invite_id: str) -> dict[str, bool]:
        def run(db: Session, admin: AppUser) -> dict[str, bool]:
            adm.revoke_invite(db, admin, adm.get(db, Invite, invite_id))
            return {"ok": True}

        return call(request, run)

    @r.post("/projects/{project_id}/codes")
    def issue_code(request: Request, project_id: str, body: CodeIn) -> dict[str, str]:
        def run(db: Session, admin: AppUser) -> dict[str, str]:
            project = adm.get(db, Project, project_id)
            return {
                "code": access_codes.issue_code(
                    db, project, admin, body.label, body.days, body.role
                )
            }

        return call(request, run)

    @r.delete("/projects/{project_id}/codes/{code_id}")
    def revoke_code(request: Request, project_id: str, code_id: str) -> dict[str, Any]:
        def run(db: Session, admin: AppUser) -> dict[str, Any]:
            project = adm.get(db, Project, project_id)
            access_codes.revoke_code(db, project, code_id, admin)
            return adm.project_detail(db, project)

        return call(request, run)

    @r.post("/projects/{project_id}/support")
    def grant_support(request: Request, project_id: str, body: SupportIn) -> dict[str, Any]:
        def run(db: Session, admin: AppUser) -> dict[str, Any]:
            project = adm.get(db, Project, project_id)
            developer = adm.get(db, AppUser, body.user)
            acc.grant_support(db, project, developer, admin, body.reason, body.hours)
            return adm.project_detail(db, project)

        return call(request, run)

    @r.delete("/projects/{project_id}/support/{user_id}")
    def revoke_support(request: Request, project_id: str, user_id: str) -> dict[str, Any]:
        def run(db: Session, admin: AppUser) -> dict[str, Any]:
            project = adm.get(db, Project, project_id)
            developer = adm.get(db, AppUser, user_id)
            acc.revoke_support(db, project, developer)
            acc.audit(
                db,
                "support_revoke",
                user=admin,
                project=project,
                payload={"to": str(developer.id)},
            )
            return adm.project_detail(db, project)

        return call(request, run)


def admin_router(auth: Auth) -> APIRouter:
    r = APIRouter(prefix=PREFIX)

    @contextmanager
    def admin_db(request: Request) -> Iterator[tuple[Session, AppUser]]:
        """A session and the admin (Auth.check already let only a superuser in); rule errors
        become HTTP answers, and nothing is written then."""
        with auth.sessions() as db:
            admin = db.get(AppUser, request.state.admin)
            if admin is None:
                raise HTTPException(403, "только для владельца платформы")
            try:
                yield db, admin
            except acc.AccessError as exc:
                db.rollback()
                raise HTTPException(409, str(exc)) from exc
            except LookupError as exc:
                db.rollback()
                raise HTTPException(404, str(exc)) from exc
            db.commit()

    def call(request: Request, fn: Callable[[Session, AppUser], T]) -> T:
        """fn in the admin's transaction: committed if it succeeds."""
        with admin_db(request) as (db, admin):
            return fn(db, admin)

    def invite_url(token: str) -> str:
        return f"{auth.config.public_url}/?invite={token}"

    _view_routes(r, call)
    _user_routes(r, call)
    _studio_routes(r, call, invite_url)
    _project_routes(r, call, invite_url)
    return r
