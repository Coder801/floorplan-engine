"""model version keeps every model file; price list keeps its YAML text

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03

Decision: docs/database.md, "Переезд проектов из папок в базу": the project lives in the database.
A model version holds every model file as written (text with comments is the truth) and a parsed
jsonb copy; the price list keeps its prices.yaml text with comments next to its parsed columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_version", sa.Column("plumbing_yaml", sa.Text(), nullable=True))
    op.add_column("model_version", sa.Column("variant_yaml", sa.Text(), nullable=True))
    op.add_column(
        "model_version",
        sa.Column(
            "data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.add_column("price_list", sa.Column("text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("price_list", "text")
    op.drop_column("model_version", "data")
    op.drop_column("model_version", "variant_yaml")
    op.drop_column("model_version", "plumbing_yaml")
