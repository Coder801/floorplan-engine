"""Question threads in the database viewer (docs/question-threads.md, step 3; docs/service-api.md,
«Треды вопросов»): the threads the caller's side sees, a thread with its chain, a message, the
studio accepting a message as the answer and closing a thread. The rules of the states are in
db/threads.py; here — who sees and writes what, and the HTTP errors: a thread of another project
or of another side is 404, a state that does not allow the action is 409 (ThreadError), the right
(`answer`, `review`) is checked by auth.check (403).

Who sees (request.state.role → viewer_db.side_of): the client side (client, client_code, viewer)
the threads of the client questions and the panel settings, the installer those of the installer
questions, the studio (owner, designer, superuser; support and a guest read only) all of them.

After an accepted message the thread is `checking`; the check itself (step 2: the AI) is a
callable given to create_viewer (check_thread), run after the response. The default leaves the
thread in `checking`.

The folder viewer (viewer.py without the database) has no threads.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from floorplan_engine.pipeline import MAX_ANSWER_TEXT
from floorplan_engine.service.api.auth import Auth
from floorplan_engine.service.api.viewer_db import Side, answer_note, request_side, sees, side_of
from floorplan_engine.service.db import questions as qs
from floorplan_engine.service.db import threads as th
from floorplan_engine.service.db.models import (
    ModelVersion,
    Project,
    Question,
    QuestionRevision,
    QuestionThread,
    ThreadMessage,
)

# The check of an accepted answer (step 2): (project id, thread id), run after the 202 response;
# it moves the thread on itself (threads.resolve, reopen, follow_up) in its own session
ThreadCheck = Callable[[uuid.UUID, uuid.UUID], None]
# The AI check backend of accepted answers: claude-code (subscription) | api (key); unset — off
ANSWER_CHECK_ENV = "SHTROBA_ANSWER_CHECK"
LAST_MESSAGES = 3  # messages of a thread in the list
# Why a thread takes no messages: only an open one is written to (decision 2026-11-28)
READ_ONLY = {
    "checking": "на проверке",
    "resolved": "решён",
    "superseded": "заменён новым тредом",
    "closed": "закрыт",
}


def no_check(project_id: uuid.UUID, thread_id: uuid.UUID) -> None:
    """No check is wired: the accepted thread stays `checking`."""


def addressee(question: Question | None) -> Side:
    """Whose answer the thread waits for: the client or the installer if asked of them, else the
    studio (a studio question, a panel setting, a free thread)."""
    audience = question.audience if question is not None else "studio"
    if audience in ("client", "installer"):
        return "client" if audience == "client" else "installer"
    return "studio"


def waiting_for(
    thread: QuestionThread, question: Question | None, messages: list[ThreadMessage]
) -> Side | None:
    """Who acts next in an open thread (not a state, a reading of its messages; decision
    2026-11-28): none yet or the last from the studio — the addressee; the last from the
    addressee or a system note (a failed check) — the studio, to decide. The quote opening a
    follow-up thread waits for the addressee. A message whose author's role is not known (an
    answer from a file) counts as the addressee's. A studio question always waits for the
    studio; a thread under the check or over — for nobody."""
    if thread.state != "open":
        return None
    to = addressee(question)
    if to == "studio" or not messages:
        return to
    last = messages[-1]
    if last.author == "system" and "quote" in last.meta:
        return to
    if last.author != "user":
        return "studio"
    by = side_of(last.role) if last.role else to
    return to if by == "studio" else "studio"


class Caller:
    """Who calls: their side, their user id or code label (to mark their own messages)."""

    def __init__(self, db: Session, auth: Auth, request: Request) -> None:
        who = auth.principal(db, request)
        self.side = request_side(request)
        self.role = str(getattr(request.state, "role", None) or "")
        self.user_id = who.user.id if who is not None and who.user is not None else None
        self.label = answer_note(who).by or ""

    def writer(self) -> th.Writer:
        return th.Writer("user", self.user_id, self.label, self.role)

    def wrote(self, message: ThreadMessage) -> bool:
        if message.author != "user":
            return False
        if self.user_id is not None:
            return message.user_id == self.user_id
        return bool(self.label) and message.user_id is None and message.author_label == self.label

    def sees(self, question: Question | None) -> bool:
        if question is None:
            return self.side == "studio"  # a free thread (later): the studio's
        return sees(self.side, question.audience, question.stage)


def _time(t: datetime | None) -> str | None:
    return t.isoformat() if t is not None else None


def _wording(db: Session, question: Question) -> QuestionRevision | None:
    return db.scalar(
        select(QuestionRevision)
        .where(QuestionRevision.question_id == question.id)
        .order_by(QuestionRevision.number.desc())
        .limit(1)
    )


def question_json(question: Question, wording: QuestionRevision | None) -> dict[str, Any]:
    """The question of a thread: its definition and latest wording; in_intake — it is in
    intake.yaml now (not removed, not superseded, not a code question)."""
    return {
        "id": question.qid,
        "text": wording.text if wording is not None else "",
        "stage": question.stage,
        "audience": question.audience,
        "kind": question.kind,
        "severity": wording.severity if wording is not None else None,
        "assumption": wording.assumption if wording is not None else None,
        "target": question.target,
        "unit": question.unit,
        "options": question.options,
        "option_labels": question.option_labels,
        "source": question.source,
        "in_intake": question.position is not None and wording is not None,
    }


def message_json(
    message: ThreadMessage, caller: Caller, accepted: uuid.UUID | None
) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "author": message.author,
        "author_label": message.author_label,
        "role": message.role,
        "text": message.text,
        "meta": message.meta,
        "created_at": _time(message.created_at),
        "mine": caller.wrote(message),
        "accepted": message.id == accepted,
    }


def thread_json(
    db: Session,
    thread: QuestionThread,
    question: Question | None,
    wording: QuestionRevision | None,
    caller: Caller,
    last: int | None = None,
) -> dict[str, Any]:
    """A thread as the caller sees it; last — only so many latest messages (the list)."""
    messages = th.messages(db, thread)
    shown = messages[-last:] if last is not None else messages
    waits = waiting_for(thread, question, messages)
    result = (
        db.get(ModelVersion, thread.result_version_id)
        if thread.result_version_id is not None
        else None
    )
    return {
        "id": str(thread.id),
        "state": thread.state,
        "question": question_json(question, wording) if question is not None else None,
        "created_at": _time(thread.created_at),
        "closed_at": _time(thread.closed_at),
        "previous_thread_id": str(thread.previous_thread_id)
        if thread.previous_thread_id is not None
        else None,
        "chain": len(th.chain(db, thread)),  # «3-й тред по вопросу»
        "accepted_message_id": str(thread.accepted_message_id)
        if thread.accepted_message_id is not None
        else None,
        "result_version": result.version if result is not None else None,
        "messages_count": len(messages),
        "messages": [message_json(m, caller, thread.accepted_message_id) for m in shown],
        "waiting_for": waits,
        "waiting_for_you": waits is not None and waits == caller.side,
    }


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _text(value: Any, field: str, required: bool) -> str:
    """A message or comment from the body: a string, not empty if required, not too long."""
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise HTTPException(422, f"{field}: нужна строка")
    text = value.strip()
    if required and not text:
        raise HTTPException(422, f"{field}: пустое сообщение")
    if len(text) > MAX_ANSWER_TEXT:
        raise HTTPException(422, f"{field}: длиннее {MAX_ANSWER_TEXT} символов")
    return text


def install_thread_routes(
    app: FastAPI,
    auth: Auth,
    project_of: Callable[[Session, Request, str], Project],
    check_thread: ThreadCheck | None = no_check,
) -> None:
    """GET /threads, GET /threads/{id}, POST …/messages, …/accept, …/close. check_thread None —
    the AI check is off (no SHTROBA_ANSWER_CHECK): accept answers 503 instead of leaving the
    thread `checking` forever."""

    def thread_of(
        db: Session, project: Project, caller: Caller, thread_id: str, lock: bool = False
    ) -> tuple[QuestionThread, Question | None]:
        """The thread of the address: of this project and seen by the caller, else 404."""
        tid = _uuid(thread_id)
        thread = db.get(QuestionThread, tid, with_for_update=lock) if tid is not None else None
        question = (
            db.get(Question, thread.question_id)
            if thread is not None and thread.question_id is not None
            else None
        )
        if thread is None or thread.project_id != project.id or not caller.sees(question):
            raise HTTPException(404, f"треда {thread_id} нет")
        return thread, question

    def one(
        db: Session, thread: QuestionThread, question: Question | None, caller: Caller
    ) -> dict[str, Any]:
        wording = _wording(db, question) if question is not None else None
        return thread_json(db, thread, question, wording, caller)

    @app.get("/api/projects/{key}/threads")
    def threads(request: Request, key: str) -> dict[str, Any]:
        """The threads of the project the caller's side sees, oldest first, with their last
        messages; waiting_for_you — how many wait for the caller."""
        with auth.db() as db:
            project = project_of(db, request, key)
            caller = Caller(db, auth, request)
            current = {c.row.id: c for c in qs.current(db, project.id).values()}
            rows = db.scalars(
                select(QuestionThread)
                .where(QuestionThread.project_id == project.id)
                .order_by(QuestionThread.created_at, QuestionThread.id)
            ).all()
            out = []
            for t in rows:
                c = current.get(t.question_id) if t.question_id is not None else None
                question = c.row if c is not None else None
                if caller.sees(question):
                    wording = c.wording if c is not None else None
                    out.append(thread_json(db, t, question, wording, caller, LAST_MESSAGES))
            return {"threads": out, "waiting_for_you": sum(t["waiting_for_you"] for t in out)}

    @app.get("/api/projects/{key}/threads/{thread_id}")
    def thread(request: Request, key: str, thread_id: str) -> dict[str, Any]:
        """A thread with all its messages and the chain before it (newest first): the unresolved
        threads of the same question, as far as the caller sees them."""
        with auth.db() as db:
            project = project_of(db, request, key)
            caller = Caller(db, auth, request)
            t, question = thread_of(db, project, caller, thread_id)
            previous = []
            for p in th.chain(db, t)[1:]:
                q = db.get(Question, p.question_id) if p.question_id is not None else None
                if caller.sees(q):
                    previous.append(one(db, p, q, caller))
            return {**one(db, t, question, caller), "previous": previous}

    @app.post("/api/projects/{key}/threads/{thread_id}/messages", status_code=201)
    def message(
        request: Request, key: str, thread_id: str, data: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """{text} — a message of the caller (right `answer`), only to an open thread: a thread on
        check or over (resolved, superseded, closed) is read-only (decision 2026-11-28)."""
        text = _text(data.get("text"), "text", required=True)
        with auth.db() as db:
            project = project_of(db, request, key)
            caller = Caller(db, auth, request)
            t, question = thread_of(db, project, caller, thread_id, lock=True)
            if t.state != "open":
                raise HTTPException(409, f"тред {READ_ONLY[t.state]}: писать в него нельзя")
            th.add_message(db, t, caller.writer(), text)
            return one(db, t, question, caller)

    @app.post("/api/projects/{key}/threads/{thread_id}/accept", status_code=202)
    def accept(
        request: Request,
        key: str,
        thread_id: str,
        data: Annotated[dict[str, Any], Body()],
        background: BackgroundTasks,
    ) -> dict[str, Any]:
        """{message_id} — the studio accepts a message as the answer (right `review`): the thread
        is `checking`, the check (check_thread) runs after the response."""
        if check_thread is None:
            raise HTTPException(503, f"проверка ответов ИИ выключена: нет {ANSWER_CHECK_ENV}")
        mid = _uuid(data.get("message_id"))
        if mid is None:
            raise HTTPException(422, "message_id: нужен id сообщения")
        with auth.db() as db:
            project = project_of(db, request, key)
            caller = Caller(db, auth, request)
            t, question = thread_of(db, project, caller, thread_id, lock=True)
            m = db.get(ThreadMessage, mid)
            if m is None:
                raise HTTPException(404, f"сообщения {mid} нет")
            try:
                th.accept(db, t, m)
            except th.ThreadError as exc:
                raise HTTPException(409, str(exc)) from exc
            body = one(db, t, question, caller)
            ids = (project.id, t.id)
        background.add_task(check_thread, *ids)  # after the commit: the check sees `checking`
        return body

    @app.post("/api/projects/{key}/threads/{thread_id}/close")
    def close(
        request: Request,
        key: str,
        thread_id: str,
        data: Annotated[dict[str, Any] | None, Body()] = None,
    ) -> dict[str, Any]:
        """{comment?} — the studio closes an open thread by hand (right `review`): solved by
        editing the sources or no longer relevant; the comment is its last message."""
        comment = _text((data or {}).get("comment"), "comment", required=False)
        with auth.db() as db:
            project = project_of(db, request, key)
            caller = Caller(db, auth, request)
            t, question = thread_of(db, project, caller, thread_id, lock=True)
            try:
                th.close(db, t, caller.writer(), comment)
            except th.ThreadError as exc:
                raise HTTPException(409, str(exc)) from exc
            return one(db, t, question, caller)
