"""вход по коду на почту: одноразовые коды

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31

Решение — docs/database.md, «Вход»: без паролей; кроме Google — код на почту.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "email_code",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS, nullable=True),
    )
    op.create_index("ix_email_code_email_created", "email_code", ["email", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_email_code_email_created", table_name="email_code")
    op.drop_table("email_code")
