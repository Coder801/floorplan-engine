"""регистрация фирмы: вид, город, телефон у studio

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31

Решение — docs/database.md, «Доступ»: фирма регистрируется отдельным шагом с названием и
видом; тип пространства — studio.kind (studio | personal), у человека — подсказка экрана.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("studio") as t:
        t.add_column(sa.Column("business", sa.String(length=20), nullable=True))
        t.add_column(sa.Column("city", sa.String(length=100), nullable=False, server_default=""))
        t.add_column(sa.Column("phone", sa.String(length=40), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("studio") as t:
        t.drop_column("phone")
        t.drop_column("city")
        t.drop_column("business")
