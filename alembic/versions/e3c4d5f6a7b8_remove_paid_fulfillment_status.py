"""remove PAID from fulfillment status enum

Fulfillment terminal states are now DELIVERED (success) and CANCELLED.
Payment is a separate axis tracked by Order.payment_state. Any historical
row with status 'PAID' is migrated to 'DELIVERED' — the payment ledger on
those rows is untouched, so the payment badge still reflects reality.

Revision ID: e3c4d5f6a7b8
Revises: bb636ea3a4c5
Create Date: 2026-10-06 21:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3c4d5f6a7b8"
down_revision: Union[str, None] = "bb636ea3a4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# New enum without PAID, matching app.models.order.OrderStatus.
_NEW_VALUES = ("INQUIRY", "CONFIRMED", "IN_PROGRESS", "READY", "DELIVERED", "CANCELLED")
_OLD_VALUES = ("INQUIRY", "CONFIRMED", "IN_PROGRESS", "READY", "DELIVERED", "PAID", "CANCELLED")


def _orders_status_enum(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name="orderstatus")


def upgrade() -> None:
    # 1. Migrate data first so no row violates the new constraint.
    op.execute("UPDATE orders SET status = 'DELIVERED' WHERE status = 'PAID'")

    # 2. Rebuild the orders table with the narrowed enum (SQLite has no
    #    ALTER for CHECK constraints, so batch mode recreates it).
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=_orders_status_enum(_OLD_VALUES),
            type_=_orders_status_enum(_NEW_VALUES),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Widen the enum again. PAID rows are not restored — the information
    # about which DELIVERED rows were once PAID is not recoverable from
    # fulfillment alone, and payment data was never lost.
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=_orders_status_enum(_NEW_VALUES),
            type_=_orders_status_enum(_OLD_VALUES),
            existing_nullable=False,
        )
