"""one workspace per person: unique membership.user_id

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-03

Decision: docs/database.md, "Access": everything belongs to one studio by its id; a person is in
one workspace — their firm, a firm as an employee or "Мой ремонт" (several firms — later).
Until now this was kept by code only.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    twice = op.get_bind().execute(
        sa.text("SELECT user_id FROM membership GROUP BY user_id HAVING count(*) > 1")
    )
    users = [str(row[0]) for row in twice]
    if users:
        raise RuntimeError(
            "пользователи в нескольких пространствах — оставьте одно и повторите: "
            + ", ".join(users)
        )
    op.create_unique_constraint("uq_membership_one_space", "membership", ["user_id"])


def downgrade() -> None:
    op.drop_constraint("uq_membership_one_space", "membership", type_="unique")
