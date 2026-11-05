"""Access to the service API (app.py), by the same rules as the viewer (`acc.project_role`,
`CAN`): not logged in gives 401, a project you cannot see gives 404 (other people's projects are
not revealed), no permission gives 403.

The check is a middleware over the path, not a line in each route: a new route under /projects is
closed from the start. A service project is tied to the access rules by a `project` row with
slug = service id; the row appears when the project is created (`register`).
"""

from __future__ import annotations

from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import Response

from floorplan_engine.service.api.auth import Auth, denied, project_access
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db.models import AuditEvent
from floorplan_engine.service.models import ProjectInfo

READ_METHODS = frozenset({"GET", "HEAD"})


def action_for(method: str, parts: list[str]) -> acc.Action:
    """What a request does; anything not named here needs the strongest right."""
    if method in READ_METHODS:
        return "view"
    if method == "POST" and parts[-1] == "answers":
        return "answer"
    return "manage"


def check(auth: Auth, request: Request) -> Response | None:
    """Service API request check; None means let it through. Paths outside /projects are not ours
    (/docs and the login routes, which `Auth.check` guards)."""
    parts = request.url.path.split("/")  # ["", "projects", id, …]
    if len(parts) < 2 or parts[1] != "projects":
        return None
    with auth.db() as db:
        who = auth.principal(db, request)
        if who is None:
            return denied(401, "нужен вход")
        if len(parts) == 2 or not parts[2]:  # the list is filtered by `visible`
            if request.method in READ_METHODS or who.user is not None:
                return None
            return denied(403, "создавать проекты можно только с учётной записью")
        key = parts[2]
        try:
            project = acc.project_by_slug(db, key)
        except acc.AccessError:
            return denied(404, f"проекта {key} нет")
        return project_access(db, who, request, key, project, action_for(request.method, parts))


def visible(auth: Auth, request: Request, ids: list[str]) -> set[str]:
    """Which of the service projects the caller sees."""
    with auth.db() as db:
        who = auth.principal(db, request)
        return set() if who is None else acc.visible_slugs(db, who, ids)


def register(auth: Auth, request: Request, info: ProjectInfo) -> None:
    """The new project goes to the caller's studio; acc.AccessError if it may not (no account type
    chosen, a client's second project)."""
    with auth.db() as db:
        who = auth.principal(db, request)
        if who is None or who.user is None:  # `check` has already refused this
            raise acc.AccessError("создавать проекты можно только с учётной записью")
        acc.create_project_for(db, who.user, info.name, info.id)


def forget(auth: Auth, request: Request, project_id: str) -> None:
    """The project is deleted, its journal stays (audit_event.project_id becomes NULL): whose it
    was and who opened it must not go with the project, so every entry keeps the project's id."""
    with auth.db() as db:
        who = auth.principal(db, request)
        project = acc.project_by_slug(db, project_id)
        if project is None:
            return
        trace = {"project_id": str(project.id), "name": project.name}
        trace["studio_id"] = str(project.studio_id)
        for event in db.scalars(select(AuditEvent).where(AuditEvent.project_id == project.id)):
            event.payload = {**event.payload, **trace}
        db.flush()
        acc.audit(db, "project_delete", user=who.user if who else None, payload=trace)
        db.delete(project)
