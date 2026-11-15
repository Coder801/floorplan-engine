"""model version keeps furniture.yaml

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-15

Decision 2026-11-15: the furniture of the flat is a model file of its own (furniture.yaml,
rectangles from the design's furniture plan); floor heating is not laid under solid furniture.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_version", sa.Column("furniture_yaml", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_version", "furniture_yaml")
