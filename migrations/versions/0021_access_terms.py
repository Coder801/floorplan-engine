"""access terms

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-28

Decision 2026-11-28 (docs/database.md, «Доступ»): a studio gives project access for 7, 30 or 90
days or without a term. project_member.expires_at is when the access ends, invite.access_days is
the term a member gets on accept. Rows written before have no term (NULL).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_member", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("invite", sa.Column("access_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("invite", "access_days")
    op.drop_column("project_member", "expires_at")
