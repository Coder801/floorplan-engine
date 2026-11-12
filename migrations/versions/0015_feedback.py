"""product feedback from the viewer

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-12

Decision 2026-11-12: viewer users leave feedback about the service itself (a bug, an idea,
other) with up to three photos; the platform superuser reads it in the admin (db/feedback.py).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("access_code_id", sa.Uuid(), nullable=True),
        sa.Column("author_label", sa.String(length=200), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("photos", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["access_code_id"], ["access_code.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_status", "feedback", ["status", "created_at"])
    op.create_index("ix_feedback_user", "feedback", ["user_id", "created_at"])
    op.create_index("ix_feedback_code", "feedback", ["access_code_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_feedback_code", table_name="feedback")
    op.drop_index("ix_feedback_user", table_name="feedback")
    op.drop_index("ix_feedback_status", table_name="feedback")
    op.drop_table("feedback")
