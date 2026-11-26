"""costing: family recipes, packaging per size, settings

Additive. Four new tables, no existing column touched.

A recipe belongs to a product FAMILY (ADR 0018) because this catalogue sells
one brownie in five sizes; per-product recipes would mean five copies and a
sixth for every new box. Packaging stays per product because it does not
scale with pieces.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recipes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("family_key", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("yield_pieces", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("labour_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overhead_per_batch", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("wastage_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("family_key", name="uq_recipes_family_key"),
    )
    op.create_index("ix_recipes_family_key", "recipes", ["family_key"])

    op.create_table(
        "recipe_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_id", "ingredient_id", name="uq_recipe_line_ingredient"),
    )
    op.create_index("ix_recipe_lines_recipe", "recipe_lines", ["recipe_id"])
    op.create_index("ix_recipe_lines_ingredient", "recipe_lines", ["ingredient_id"])

    op.create_table(
        "product_packaging",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("cost", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_packaging_product", "product_packaging", ["product_id"])

    op.create_table(
        "costing_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "labour_rate_per_hour", sa.Numeric(10, 2), nullable=False, server_default="100"
        ),
        sa.Column("default_wastage_pct", sa.Numeric(5, 2), nullable=False, server_default="5"),
        sa.Column("target_margin_pct", sa.Numeric(5, 2), nullable=False, server_default="40"),
        sa.Column("gst_mode", sa.String(length=12), nullable=False, server_default="exclusive"),
        sa.Column("price_rounding", sa.String(length=12), nullable=False, server_default="five"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("costing_settings")
    op.drop_index("ix_product_packaging_product", table_name="product_packaging")
    op.drop_table("product_packaging")
    op.drop_index("ix_recipe_lines_ingredient", table_name="recipe_lines")
    op.drop_index("ix_recipe_lines_recipe", table_name="recipe_lines")
    op.drop_table("recipe_lines")
    op.drop_index("ix_recipes_family_key", table_name="recipes")
    op.drop_table("recipes")
