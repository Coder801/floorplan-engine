"""installation by tasks: work plan, tasks, lines, photos, comments, payments

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-11

Decision: docs/work-tasks.md. The approved project is split into installation tasks made from the
.epd work_plan draft; the state of the work (statuses, fact, photos, comments, payments) lives only
here. Sums are not stored: the code counts them from the lines.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _user(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([name], ["app_user.id"], ondelete="SET NULL")


def _task() -> list[sa.SchemaItem]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["work_task.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    ]


def upgrade() -> None:
    op.create_table(
        "work_plan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=True),
        sa.Column("build_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_label", sa.String(length=200), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_version.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["build_id"], ["build.id"], ondelete="SET NULL"),
        _user("created_by"),
        _user("approved_by"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_work_plan_active",
        "work_plan",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("state <> 'closed'"),
    )
    op.create_table(
        "work_task",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=True),
        sa.Column("domain", sa.String(length=20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("extra", sa.Boolean(), nullable=False),
        sa.Column("photo", sa.String(length=10), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("materials_included", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["work_plan.id"], ondelete="CASCADE"),
        _user("assignee_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_task_plan", "work_task", ["plan_id", "position"])
    op.create_table(
        "work_line",
        *_task(),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("plan_qty", sa.Float(), nullable=False),
        sa.Column("fact_qty", sa.Float(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
    )
    op.create_index("ix_work_line_task", "work_line", ["task_id", "position"])
    op.create_table(
        "work_photo",
        *_task(),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("target", sa.String(length=100), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("author_label", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _user("user_id"),
    )
    op.create_index("ix_work_photo_task", "work_photo", ["task_id", "created_at"])
    op.create_table(
        "work_comment",
        *_task(),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("author_label", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _user("user_id"),
    )
    op.create_index("ix_work_comment_task", "work_comment", ["task_id", "created_at"])
    op.create_table(
        "work_payment",
        *_task(),
        sa.Column("amount", sa.Numeric(precision=12, scale=2, asdecimal=False), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _user("recorded_by"),
    )
    op.create_index("ix_work_payment_task", "work_payment", ["task_id", "created_at"])


def downgrade() -> None:
    for table in ("work_payment", "work_comment", "work_photo", "work_line"):
        op.drop_index(f"ix_{table}_task", table_name=table)
        op.drop_table(table)
    op.drop_index("ix_work_task_plan", table_name="work_task")
    op.drop_table("work_task")
    op.drop_index("uq_work_plan_active", table_name="work_plan")
    op.drop_table("work_plan")
