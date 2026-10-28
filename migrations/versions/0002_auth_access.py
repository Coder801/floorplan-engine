"""вход и доступ: OAuth, сессии, участники проекта, приглашения, поддержка, журнал

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28

Решения — docs/database.md, разделы «Доступ» и «Вход». price_list пересоздаётся (свой id,
прайс студии или проекта): база ещё не подключена к сервису, данных в ней нет.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
TS = sa.DateTime(timezone=True)


def _user_fk(ondelete: str) -> sa.ForeignKey:
    return sa.ForeignKey("app_user.id", ondelete=ondelete)


def upgrade() -> None:
    with op.batch_alter_table("app_user") as t:
        t.alter_column("email", existing_type=sa.String(length=320), nullable=True)
        t.add_column(sa.Column("name", sa.String(length=200), nullable=False, server_default=""))
        t.add_column(sa.Column("account_type", sa.String(length=10), nullable=True))
        t.add_column(
            sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        t.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
        t.add_column(sa.Column("last_login_at", TS, nullable=True))
    with op.batch_alter_table("studio") as t:
        t.add_column(
            sa.Column("kind", sa.String(length=20), nullable=False, server_default="studio")
        )
    with op.batch_alter_table("membership") as t:
        t.add_column(
            sa.Column("created_at", TS, nullable=False, server_default=sa.func.current_timestamp())
        )
    with op.batch_alter_table("project") as t:
        t.add_column(sa.Column("slug", sa.String(length=100), nullable=True))
        t.create_unique_constraint("uq_project_slug", ["slug"])
    with op.batch_alter_table("model_version") as t:
        t.add_column(sa.Column("wiring_yaml", sa.Text(), nullable=True))
        t.add_column(sa.Column("user_id", sa.Uuid(), nullable=True))
        t.create_foreign_key(
            "fk_model_version_user", "app_user", ["user_id"], ["id"], ondelete="SET NULL"
        )

    op.create_table(
        "oauth_account",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("provider", "provider_user_id"),
    )
    op.create_table(
        "user_session",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("user_agent", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
    )
    op.create_table(
        "project_member",
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("invited_by", sa.Uuid(), _user_fk("SET NULL"), nullable=True),
        sa.Column("created_at", TS, nullable=False),
    )
    # Клиент — только в одном проекте
    op.create_index(
        "uq_project_member_one_client",
        "project_member",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("role = 'client'"),
        sqlite_where=sa.text("role = 'client'"),
    )
    op.create_table(
        "invite",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "studio_id", sa.Uuid(), sa.ForeignKey("studio.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("invited_by", sa.Uuid(), _user_fk("SET NULL"), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column(
            "accepted_by",
            sa.Uuid(),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("accepted_at", TS, nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
        sa.CheckConstraint(
            "(studio_id IS NULL) <> (project_id IS NULL)", name="invite_studio_or_project"
        ),
    )
    op.create_table(
        "support_grant",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("granted_by", sa.Uuid(), _user_fk("SET NULL"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS, nullable=True),
    )
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("user_id", sa.Uuid(), _user_fk("SET NULL"), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_audit_event_project", "audit_event", ["project_id", "created_at"])

    op.drop_table("price_list")
    op.create_table(
        "price_list",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "studio_id",
            sa.Uuid(),
            sa.ForeignKey("studio.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("date", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("items", JSON, nullable=False),
        sa.Column("board_kit", JSON, nullable=False),
        sa.CheckConstraint(
            "(studio_id IS NULL) <> (project_id IS NULL)", name="price_list_studio_or_project"
        ),
    )


def downgrade() -> None:
    op.drop_table("price_list")
    op.create_table(
        "price_list",
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("date", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("items", JSON, nullable=False),
        sa.Column("board_kit", JSON, nullable=False),
    )
    op.drop_index("ix_audit_event_project", table_name="audit_event")
    op.drop_table("audit_event")
    op.drop_table("support_grant")
    op.drop_table("invite")
    op.drop_index("uq_project_member_one_client", table_name="project_member")
    op.drop_table("project_member")
    op.drop_table("user_session")
    op.drop_table("oauth_account")
    with op.batch_alter_table("model_version") as t:
        t.drop_constraint("fk_model_version_user", type_="foreignkey")
        t.drop_column("user_id")
        t.drop_column("wiring_yaml")
    with op.batch_alter_table("project") as t:
        t.drop_constraint("uq_project_slug", type_="unique")
        t.drop_column("slug")
    with op.batch_alter_table("membership") as t:
        t.drop_column("created_at")
    with op.batch_alter_table("studio") as t:
        t.drop_column("kind")
    with op.batch_alter_table("app_user") as t:
        t.drop_column("last_login_at")
        t.drop_column("is_active")
        t.drop_column("is_superuser")
        t.drop_column("account_type")
        t.drop_column("name")
        t.alter_column("email", existing_type=sa.String(length=320), nullable=False)
