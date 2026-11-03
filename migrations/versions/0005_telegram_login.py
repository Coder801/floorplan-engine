"""Telegram login: user phone number and login tickets

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-01

Decision: docs/database.md, "Login": the account is keyed by phone number, the number is
confirmed by the Telegram bot (user contact); a login ticket links the page, the bot chat and the
number.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("app_user") as t:
        t.add_column(sa.Column("phone", sa.String(length=20), nullable=True))
        t.create_unique_constraint("uq_app_user_phone", ["phone"])
    op.create_table(
        "login_ticket",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("lang", sa.String(length=5), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_user_id", sa.String(length=32), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_login_ticket_chat", "login_ticket", ["chat_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_login_ticket_chat", table_name="login_ticket")
    op.drop_table("login_ticket")
    with op.batch_alter_table("app_user") as t:
        t.drop_constraint("uq_app_user_phone", type_="unique")
        t.drop_column("phone")
