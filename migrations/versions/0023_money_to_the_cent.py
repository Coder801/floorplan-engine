"""money to the cent

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-28

Decision 2026-11-28 (docs/database.md, «Деньги»): money is stored exactly to the cent. The work
line price becomes numeric(12, 2) (as work_payment.amount already is), rounded half up; the
prices of the parsed price list copy (`price_list.items`, `board_kit`) are rounded to the cent in
place. The prices.yaml text is not touched: it is what the studio wrote, the estimate rounds what
it reads. Downgrade turns the price back into a float; rounded JSON prices stay rounded.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _cents(value: float) -> float:
    # as model/money.cents: the shortest decimal of the float, half up
    return float(Decimal(repr(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _price(value: Any) -> Any:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return _cents(value) if isinstance(value, float) else value
    if isinstance(value, dict) and isinstance(value.get("price"), float):
        return {**value, "price": _cents(value["price"])}
    return value


def upgrade() -> None:
    op.alter_column(
        "work_line",
        "price",
        type_=sa.Numeric(12, 2),
        existing_type=sa.Float(),
        existing_nullable=True,
        postgresql_using="round(price::numeric, 2)",
    )
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, items, board_kit FROM price_list")).all()
    for row_id, items, board_kit in rows:
        new_items = {k: _price(v) for k, v in (items or {}).items()}
        new_kit = [_price(v) for v in (board_kit or [])]
        if new_items != items or new_kit != board_kit:
            bind.execute(
                sa.text(
                    "UPDATE price_list SET items = CAST(:items AS jsonb), "
                    "board_kit = CAST(:kit AS jsonb) WHERE id = :id"
                ),
                {"items": json.dumps(new_items), "kit": json.dumps(new_kit), "id": row_id},
            )


def downgrade() -> None:
    op.alter_column(
        "work_line",
        "price",
        type_=sa.Float(),
        existing_type=sa.Numeric(12, 2),
        existing_nullable=True,
        postgresql_using="price::double precision",
    )
