"""studio folder: each studio's project files in its own folder of the viewer root

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03

Decision: docs/database.md, "Access": the price list (prices.yaml) and the profile (studio.yaml)
live in the studio folder next to its projects, so studios do not share them. Until now every
project lived in the root: the studios that already have projects keep the root ("").
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("studio", sa.Column("folder", sa.String(length=100), nullable=True))
    op.execute(
        "UPDATE studio SET folder = '' "
        "WHERE kind = 'unowned' OR id IN (SELECT studio_id FROM project)"
    )


def downgrade() -> None:
    op.drop_column("studio", "folder")
