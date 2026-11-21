"""b2b channel: accounts, contracts, price lists, order terms

Additive only — no existing column changes meaning and no data is moved.

- New tables: b2b_accounts, b2b_contracts, b2b_price_items, b2b_order_terms
- orders gains `channel` (NOT NULL DEFAULT 'RETAIL') and `account_id` (NULL)
- invoices gains `billed_to_gstin` and `po_reference` (NOT NULL DEFAULT '')

`orders.account_id` is added with a plain ALTER TABLE, deliberately without
an inline REFERENCES clause: adding a foreign key on SQLite requires
rebuilding the table, and a batch rebuild reflects the schema without the
CHECK constraint that guards `orders.status`. The ORM still declares the
foreign key (so a fresh database created by create_all has it), and
accounts are soft-deleted, never deleted, so nothing can be orphaned.

Revision ID: c7d8e9f0a1b2
Revises: e3c4d5f6a7b8
Create Date: 2026-11-21 15:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "e3c4d5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACCOUNT_KIND = sa.Enum("SHOP", "FRANCHISEE", "DISTRIBUTOR", name="accountkind")
_PRICING_MODE = sa.Enum("UNIT_PRICE", "COMMISSION", name="pricingmode")
_PAYMENT_TERMS = sa.Enum("ADVANCE", "CREDIT", "COD", name="paymentterms")


def upgrade() -> None:
    # --- 1. Partners -------------------------------------------------
    op.create_table(
        "b2b_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", _ACCOUNT_KIND, nullable=False, server_default="SHOP"),
        sa.Column("gstin", sa.String(20), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("email", sa.String(120), nullable=True),
        sa.Column("billing_address", sa.Text(), nullable=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("min_order_value", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("order_cutoff", sa.String(5), nullable=False, server_default="18:00"),
        sa.Column("lead_time_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("credit_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credit_limit", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column(
            "dispatch_days", sa.String(20), nullable=False, server_default="1,2,3,4,5,6"
        ),
        sa.Column(
            "production_mode", sa.String(10), nullable=False, server_default="SHARED"
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_b2b_accounts_code_active",
        "b2b_accounts",
        ["code"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
    )
    op.create_index("ix_b2b_accounts_is_active", "b2b_accounts", ["is_active"])

    # --- 2. Contracts ------------------------------------------------
    op.create_table(
        "b2b_contracts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("b2b_accounts.id"),
            nullable=False,
        ),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("pricing_mode", _PRICING_MODE, nullable=False, server_default="UNIT_PRICE"),
        sa.Column("default_commission_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("min_order_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("credit_days", sa.Integer(), nullable=True),
        sa.Column("credit_limit", sa.Numeric(12, 2), nullable=True),
        sa.Column("terms_note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_b2b_contracts_account", "b2b_contracts", ["account_id", "effective_from"]
    )

    # --- 3. Price list -----------------------------------------------
    op.create_table(
        "b2b_price_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "contract_id",
            sa.Integer(),
            sa.ForeignKey("b2b_contracts.id"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("min_qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("commission_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("gst_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("contract_id", "product_id", "min_qty", name="uq_b2b_price_slab"),
    )
    op.create_index(
        "ix_b2b_price_lookup", "b2b_price_items", ["contract_id", "product_id", "min_qty"]
    )

    # --- 4. Orders: channel + partner --------------------------------
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("channel", sa.String(10), nullable=False, server_default="RETAIL")
        )
        batch_op.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_orders_channel", ["channel"])
        batch_op.create_index("ix_orders_account_id", ["account_id"])

    # --- 5. Per-order B2B terms --------------------------------------
    op.create_table(
        "b2b_order_terms",
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("b2b_accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "contract_id", sa.Integer(), sa.ForeignKey("b2b_contracts.id"), nullable=True
        ),
        sa.Column("po_reference", sa.String(60), nullable=True),
        sa.Column("dispatch_date", sa.Date(), nullable=True),
        sa.Column("payment_terms", _PAYMENT_TERMS, nullable=False, server_default="CREDIT"),
        sa.Column("credit_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "production_mode", sa.String(10), nullable=False, server_default="SHARED"
        ),
        sa.Column("warnings_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("price_snapshot", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_b2b_order_terms_account", "b2b_order_terms", ["account_id"])

    # --- 6. Invoices: buyer GSTIN + PO reference ---------------------
    with op.batch_alter_table("invoices", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("billed_to_gstin", sa.String(20), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("po_reference", sa.String(60), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("invoices", schema=None) as batch_op:
        batch_op.drop_column("po_reference")
        batch_op.drop_column("billed_to_gstin")

    op.drop_index("ix_b2b_order_terms_account", table_name="b2b_order_terms")
    op.drop_table("b2b_order_terms")

    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_index("ix_orders_account_id")
        batch_op.drop_index("ix_orders_channel")
        batch_op.drop_column("account_id")
        batch_op.drop_column("channel")

    op.drop_index("ix_b2b_price_lookup", table_name="b2b_price_items")
    op.drop_table("b2b_price_items")
    op.drop_index("ix_b2b_contracts_account", table_name="b2b_contracts")
    op.drop_table("b2b_contracts")
    op.drop_index("ix_b2b_accounts_is_active", table_name="b2b_accounts")
    op.drop_index("uq_b2b_accounts_code_active", table_name="b2b_accounts")
    op.drop_table("b2b_accounts")
