"""project name (slug) is unique inside a studio, not in the whole database

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03

Decision: docs/database.md, "Переезд проектов из папок в базу": projects are addressed by id, so
two studios may each have their own kv42.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_project_slug", "project", type_="unique")
    op.create_unique_constraint("uq_project_studio_slug", "project", ["studio_id", "slug"])


def downgrade() -> None:
    # Fails if two studios already have a project with the same name: rename one first
    op.drop_constraint("uq_project_studio_slug", "project", type_="unique")
    op.create_unique_constraint("uq_project_slug", "project", ["slug"])
