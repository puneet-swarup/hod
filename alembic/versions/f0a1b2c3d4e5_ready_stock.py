"""finished-goods stock ledger

Baking to stock is production that is not tied to an order. The ingredient
side already has a ledger; this adds the same idea one level up, so
"how many brownies are ready right now?" has an answer that can be audited.

Additive: one new table, nothing existing touched.

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_stock_movements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "PRODUCTION",
                "SALE",
                "WASTAGE",
                "RETURN",
                "ADJUSTMENT",
                name="productmovementreason",
            ),
            nullable=False,
        ),
        sa.Column("reference_type", sa.String(length=20), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_stock_product", "product_stock_movements", ["product_id"])
    op.create_index("ix_product_stock_created", "product_stock_movements", ["created_at"])
    op.create_index(
        "ix_product_stock_reference",
        "product_stock_movements",
        ["reference_type", "reference_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_stock_reference", table_name="product_stock_movements")
    op.drop_index("ix_product_stock_created", table_name="product_stock_movements")
    op.drop_index("ix_product_stock_product", table_name="product_stock_movements")
    op.drop_table("product_stock_movements")
