"""services of a project

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-23

Decision 2026-11-23 (docs/database.md, «Сервисы проекта»): a project has a list of enabled
services (electrical, plumbing, demolition — service/db/services.py), the admin ticks them and
the viewer hides the sections of the services that are off. NULL is all of them: the existing
projects lose nothing.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project",
        sa.Column("services", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project", "services")
