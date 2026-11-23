"""cost on the finished-goods ledger

Baking to stock recorded the ingredient cost against the bake, not against
the goods. An order selling from the shelf therefore had COGS 0, and the
month that baked carried cost with no matching revenue.

This adds ``unit_cost`` to every finished-goods movement: the recipe cost
at bake time on a PRODUCTION row, the average cost of the stock being
consumed on a SALE or WASTAGE row. Cost now follows the goods.

Additive. Existing rows keep NULL, which reads as "unknown cost" and
contributes nothing — the same behaviour as before this migration.

Revision ID: a1b2c3d4e5f6
Revises: f0a1b2c3d4e5
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_stock_movements",
        sa.Column("unit_cost", sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("product_stock_movements") as batch_op:
        batch_op.drop_column("unit_cost")
