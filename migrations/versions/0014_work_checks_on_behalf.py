"""installation by tasks: acceptance ticks, acting for the client

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-12

Decisions 2026-11-12 (docs/work-tasks.md): ticks of the acceptance criterion are kept
(work_task.checked — indexes of result items); the studio approves a plan, accepts, returns or
agrees an extra task for the client only with the channel of the client's confirmation
(work_plan.approved_on_behalf, work_comment.on_behalf, with a note).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_task",
        sa.Column(
            "checked",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("work_plan", sa.Column("approved_on_behalf", sa.String(length=10)))
    op.add_column(
        "work_plan", sa.Column("approved_note", sa.Text(), nullable=False, server_default="")
    )
    op.add_column("work_comment", sa.Column("on_behalf", sa.String(length=10)))
    op.add_column(
        "work_comment", sa.Column("on_behalf_note", sa.Text(), nullable=False, server_default="")
    )


def downgrade() -> None:
    op.drop_column("work_comment", "on_behalf_note")
    op.drop_column("work_comment", "on_behalf")
    op.drop_column("work_plan", "approved_note")
    op.drop_column("work_plan", "approved_on_behalf")
    op.drop_column("work_task", "checked")
