"""variant label on products

One product row per sellable unit stays as it is — order lines, recipes and
partner price lists all point at a product, and changing that would be a
rewrite. What changes is that products sharing a name are treated as sizes
of one thing, and ``variant_label`` holds the size ("9 pc", "1 kg").

No data is guessed: existing duplicate-name products get a NULL label and
are labelled from the product form, where all sizes of a family are shown
together.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: str | Sequence[str] | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("variant_label", sa.String(30), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("variant_label")
