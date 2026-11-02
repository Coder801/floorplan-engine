"""код доступа к проекту: вход в просмотр одного проекта без учётки

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-02

Решение — docs/database.md, «Вход»: студия выдаёт код, человек вводит его на экране входа
и смотрит этот проект (только чтение). В базе — только sha256 кода.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "access_code",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uses", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_access_code_project", "access_code", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_access_code_project", table_name="access_code")
    op.drop_table("access_code")
