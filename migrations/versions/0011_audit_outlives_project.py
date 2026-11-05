"""the audit journal outlives a deleted project

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-05

Deleting a project used to delete its journal too, support access entries included.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK = "audit_event_project_id_fkey"


def _project_fk(ondelete: str) -> None:
    op.drop_constraint(FK, "audit_event", type_="foreignkey")
    op.create_foreign_key(FK, "audit_event", "project", ["project_id"], ["id"], ondelete=ondelete)


def upgrade() -> None:
    _project_fk("SET NULL")


def downgrade() -> None:
    _project_fk("CASCADE")
