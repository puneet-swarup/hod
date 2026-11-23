"""list price on order items; clear the balance on cancelled orders

Two changes, both additive in the sense that no existing value is
reinterpreted:

1. ``order_items.list_price`` — what the product was configured at when the
   line was sold, next to ``unit_price`` which is what was actually charged.
   Existing rows are backfilled from ``unit_price``: every past line was
   sold at list, because an override was not possible before this release.

2. ``orders.balance_due`` is set to 0 on cancelled orders. Cancelling never
   cleared it, so a cancelled order kept advertising money it could not
   collect — ₹4,660 across five orders in the live database at the time.
   ``advance_paid`` is deliberately left alone: it is the record of cash
   actually taken, and it is what a refund would be measured against.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: str | Sequence[str] | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("list_price", sa.Numeric(10, 2), nullable=True),
    )

    # Every line written before this release was sold at the configured
    # price — an override was not possible — so the backfill is exact.
    op.execute("UPDATE order_items SET list_price = unit_price WHERE list_price IS NULL")

    # Cancelled orders cannot be owed money. Keep advance_paid (cash taken).
    op.execute("UPDATE orders SET balance_due = 0 WHERE status = 'CANCELLED'")


def downgrade() -> None:
    # The cancelled-order balances cannot be reconstructed, and that is
    # acceptable: they were wrong. Only the column is removed.
    with op.batch_alter_table("order_items") as batch_op:
        batch_op.drop_column("list_price")
