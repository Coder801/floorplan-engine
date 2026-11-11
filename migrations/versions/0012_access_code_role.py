"""access code role: view or client

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-11

A code used to be read only. Now it has a role: viewer (as before, the default for existing
codes) or client_code — the studio client sets the project up without an account.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "access_code",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="viewer"),
    )


def downgrade() -> None:
    op.drop_column("access_code", "role")
