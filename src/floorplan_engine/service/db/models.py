"""Service database tables (SQLAlchemy 2): Postgres in production, SQLite in tests.

The schema follows the ER diagram in docs/database.md. YAML stays the project model format:
the database stores its versions (model_version), and the core still builds the drawing from
a folder. Files (sources, DXF, .epd, PNG, symbol samples) live in object storage: the database
holds only the object_key.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSON is jsonb: indexes and queries inside it (Postgres only)
Json = JSONB()


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: Json, list[Any]: Json}


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=now)


# --- Studios and access (docs/database.md, "Access" and "Login") --------------------------


class Studio(Base):
    """Project workspace: a studio or installer (`studio`), or the personal workspace of a flat
    owner (`personal`, one project). The access boundary is the studio."""

    __tablename__ = "studio"
    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="studio")  # studio | personal | unowned
    # Firm (kind = studio) at registration: kind, city, phone (access.register_firm)
    business: Mapped[str | None] = mapped_column(String(20))  # design | electric | …
    city: Mapped[str] = mapped_column(String(100), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    # Folder of the studio's projects in the viewer root (access.studio_folder): None — its own
    # folder named by id, "" — the root itself (the operator's projects/, access.claim_root)
    folder: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = _created()
    profile: Mapped[StudioProfile | None] = relationship(back_populates="studio")
    projects: Mapped[list[Project]] = relationship(back_populates="studio")


class AppUser(Base):
    """User (user is a reserved word in Postgres). No passwords: login through OAuth
    (oauth_account). email may be empty, not every provider returns it; phone comes from the
    Telegram login (db/telegram_login.py), "+380…"."""

    __tablename__ = "app_user"
    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    # client is a flat owner, pro is a studio or installer; None means not chosen yet
    account_type: Mapped[str | None] = mapped_column(String(10))
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)  # sees everything
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class OAuthAccount(Base):
    """Account at a login provider (google, …), linked to a user."""

    __tablename__ = "oauth_account"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(20))
    provider_user_id: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = _created()


class UserSession(Base):
    """Login session: the cookie holds a random token, the table only its sha256."""

    __tablename__ = "user_session"
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_agent: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EmailCode(Base):
    """E-mail login code (db/email_codes.py): one-time, 6 digits, only the sha256 of "email:code" is
    stored; entry attempts and send time are kept for limits."""

    __tablename__ = "email_code"
    __table_args__ = (Index("ix_email_code_email_created", "email", "created_at"),)
    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(String(320))
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginTicket(Base):
    """Telegram login (db/telegram_login.py): the page gives the link t.me/<bot>?start=<token>, the
    bot remembers the chat on "/start token" and the phone on contact; the page polls the ticket
    and logs in. Only the sha256 of the token is stored."""

    __tablename__ = "login_ticket"
    __table_args__ = (Index("ix_login_ticket_chat", "chat_id", "created_at"),)
    id: Mapped[uuid.UUID] = _id()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    lang: Mapped[str] = mapped_column(String(5), default="ru")
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_user_id: Mapped[str | None] = mapped_column(String(32))
    phone: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Membership(Base):
    """A person in a workspace (studio.id is the key): the owner of a firm or of "Мой ремонт",
    or a firm employee. One workspace per person (several firms — later): the unique user_id."""

    __tablename__ = "membership"
    __table_args__ = (UniqueConstraint("user_id", name="uq_membership_one_space"),)
    studio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20))  # owner | designer | installer
    created_at: Mapped[datetime] = _created()


class StudioProfile(Base):
    """Studio profile: what currently lives in projects/studio.yaml."""

    __tablename__ = "studio_profile"
    studio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("studio.id", ondelete="CASCADE"), primary_key=True
    )
    organization: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[str] = mapped_column(String(40), default="")
    signatures: Mapped[list[Any]] = mapped_column(default=list)
    studio: Mapped[Studio] = relationship(back_populates="profile")


class Symbol(Base):
    """Studio symbol sample for recognising electrical points on sheets."""

    __tablename__ = "symbol"
    id: Mapped[uuid.UUID] = _id()
    studio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("studio.id", ondelete="CASCADE"))
    point_type: Mapped[str] = mapped_column(String(40))  # socket | switch | …
    object_key: Mapped[str] = mapped_column(Text)


# --- Project and sources -------------------------------------------------------------


class Project(Base):
    __tablename__ = "project"
    # The name (slug) is unique inside a studio: two studios may each have their own kv42
    __table_args__ = (UniqueConstraint("studio_id", "slug", name="uq_project_studio_slug"),)
    id: Mapped[uuid.UUID] = _id()
    studio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("studio.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    # Project folder in the viewer (projects/<slug>), while projects live in folders; for a
    # project of the service API (api/app.py) — its id in Storage
    slug: Mapped[str | None] = mapped_column(String(100))
    # State: values of service.models.ProjectState
    state: Mapped[str] = mapped_column(String(20), default="created")
    message: Mapped[str] = mapped_column(Text, default="")
    round: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    studio: Mapped[Studio] = relationship(back_populates="projects")
    sources: Mapped[list[Source]] = relationship(back_populates="project")


class ProjectMember(Base):
    """Access to one project: a client (flat owner) or an outside installer.
    A client is in one project only (partial unique index)."""

    __tablename__ = "project_member"
    __table_args__ = (
        Index(
            "uq_project_member_one_client",
            "user_id",
            unique=True,
            postgresql_where=text("role = 'client'"),
        ),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20))  # client | installer
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class Invite(Base):
    """Invite link to a studio or a project; only the sha256 of the token is stored."""

    __tablename__ = "invite"
    __table_args__ = (
        CheckConstraint(
            "(studio_id IS NULL) <> (project_id IS NULL)", name="invite_studio_or_project"
        ),
    )
    id: Mapped[uuid.UUID] = _id()
    studio_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("studio.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(320))  # who it was sent to, for the list
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccessCode(Base):
    """Project access code (db/access_codes.py): the studio issues a code, a person enters it on the
    login screen and opens that one project without an account. role: viewer — read only,
    client_code — the client also answers and sets the project up (decision 2026-11-11). Only the
    sha256 of the code is stored; label says who it was given to, for the list."""

    __tablename__ = "access_code"
    __table_args__ = (Index("ix_access_code_project", "project_id", "created_at"),)
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(20), default="viewer", server_default="viewer")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uses: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportGrant(Base):
    """Developer access to someone else's project: granted by the studio owner, with a reason and
    a term.
    """

    __tablename__ = "support_grant"
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    """Audit log: logins, answers, route edits, builds, invites, downloads, support."""

    __tablename__ = "audit_event"
    __table_args__ = (Index("ix_audit_event_project", "project_id", "created_at"),)
    id: Mapped[uuid.UUID] = _id()
    # SET NULL: the journal outlives the project (project_guard.forget keeps its id in payload)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = _created()


class Source(Base):
    __tablename__ = "source"
    __table_args__ = (UniqueConstraint("project_id", "sha256"),)
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    file_name: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))  # vector | raster | image | text | sketch
    pages: Mapped[int] = mapped_column(Integer, default=0)
    object_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    project: Mapped[Project] = relationship(back_populates="sources")


class FactsPage(Base):
    """Source page digest (facts.analysis.to_dict), cached by hash and algorithm version.
    The summary (scale, number of dimensions, confidence) is in columns: the "failed" gate and
    cross-project queries use it."""

    __tablename__ = "facts_page"
    __table_args__ = (UniqueConstraint("source_id", "page", "algo_version"),)
    id: Mapped[uuid.UUID] = _id()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"))
    page: Mapped[int] = mapped_column(Integer)
    algo_version: Mapped[str] = mapped_column(String(20))
    adapter: Mapped[str] = mapped_column(String(10))  # vector | raster
    unit: Mapped[str] = mapped_column(String(4))
    scale_mm: Mapped[float | None] = mapped_column(Float)
    scale_dims: Mapped[int] = mapped_column(Integer, default=0)
    dims_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    facts: Mapped[dict[str, Any]] = mapped_column()
    created_at: Mapped[datetime] = _created()


# --- Model, questions, builds ------------------------------------------------------


class ModelVersion(Base):
    """Project model version: YAML texts, who wrote them and when. The text is the truth
    (comments like "# PDF, масштаб" and the field order survive, a pull writes the files back
    byte for byte); `data` is a parsed copy by file name for queries and the admin."""

    __tablename__ = "model_version"
    __table_args__ = (UniqueConstraint("project_id", "version"),)
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    room_yaml: Mapped[str | None] = mapped_column(Text)
    electrical_yaml: Mapped[str | None] = mapped_column(Text)
    intake_yaml: Mapped[str | None] = mapped_column(Text)
    answers_yaml: Mapped[str | None] = mapped_column(Text)
    wiring_yaml: Mapped[str | None] = mapped_column(Text)  # route edits from the viewer
    plumbing_yaml: Mapped[str | None] = mapped_column(Text)
    variant_yaml: Mapped[str | None] = mapped_column(Text)  # wiring variant chosen in the viewer
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    author: Mapped[str] = mapped_column(String(20))  # analyzer | user | operator
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class Round(Base):
    __tablename__ = "round"
    __table_args__ = (UniqueConstraint("project_id", "number"),)
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_version.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class Question(Base):
    __tablename__ = "question"
    __table_args__ = (UniqueConstraint("round_id", "qid"),)
    id: Mapped[uuid.UUID] = _id()
    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("round.id", ondelete="CASCADE"))
    qid: Mapped[str] = mapped_column(String(20))  # q1, q2… from intake.yaml
    stage: Mapped[str] = mapped_column(String(20))
    target: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10))  # critical | major | minor
    text: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="open")  # open | answered | …


class Answer(Base):
    __tablename__ = "answer"
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question.id", ondelete="CASCADE"), primary_key=True
    )
    value: Mapped[dict[str, Any]] = mapped_column()  # {"value": 1800} | {"accept": true} | …
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class Build(Base):
    """A build_project run for a model version: report (report.json) and status."""

    __tablename__ = "build"
    id: Mapped[uuid.UUID] = _id()
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_version.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(20))  # built | insufficient | failed
    report: Mapped[dict[str, Any]] = mapped_column()
    created_at: Mapped[datetime] = _created()
    files: Mapped[list[BuildFile]] = relationship(back_populates="build")


class BuildFile(Base):
    """Build file: dxf, epd, png, estimate, csv; the file itself is in object storage."""

    __tablename__ = "build_file"
    id: Mapped[uuid.UUID] = _id()
    build_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("build.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(Text)  # path inside out/: project.dxf, estimate.csv…
    object_key: Mapped[str] = mapped_column(Text)
    build: Mapped[Build] = relationship(back_populates="files")


class PriceList(Base):
    """Price list: what currently lives in prices.yaml, the project's own or the studio's shared
    one (projects/prices.yaml)."""

    __tablename__ = "price_list"
    __table_args__ = (
        CheckConstraint(
            "(studio_id IS NULL) <> (project_id IS NULL)", name="price_list_studio_or_project"
        ),
    )
    id: Mapped[uuid.UUID] = _id()
    studio_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("studio.id", ondelete="CASCADE"), unique=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), unique=True
    )
    currency: Mapped[str] = mapped_column(String(8), default="грн")
    date: Mapped[str] = mapped_column(String(20), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    items: Mapped[dict[str, Any]] = mapped_column(default=dict)
    board_kit: Mapped[list[Any]] = mapped_column(default=list)
    # prices.yaml as written, with its comments: the truth; the columns above are its parsed copy
    text: Mapped[str | None] = mapped_column(Text)


class Usage(Base):
    """LLM usage: what is currently written to the project's usage.jsonl; the basis for billing."""

    __tablename__ = "usage"
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    round: Mapped[int] = mapped_column(Integer)
    backend: Mapped[str] = mapped_column(String(20))  # claude-code | api
    model: Mapped[str] = mapped_column(String(60), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 4, asdecimal=False), default=0)
    created_at: Mapped[datetime] = _created()
