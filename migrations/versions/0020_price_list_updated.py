"""price list updated time

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-28

Decision 2026-11-28 (docs/database.md, «Админка»): the admin shows when a studio price list was
last written. Rows written before the column have no time (NULL).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("price_list", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("price_list", "updated_at")
