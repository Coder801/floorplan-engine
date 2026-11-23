"""access code value

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-23

Decision 2026-11-23 (docs/database.md, «Код доступа к проекту»): the code itself is kept next to
its sha256, so the admin can copy an issued code from the project's list. Login still looks the
code up by the hash. Codes issued before have no value (NULL): it cannot be recovered from the
hash.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("access_code", sa.Column("code", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("access_code", "code")
