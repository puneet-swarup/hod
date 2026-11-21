"""B2B channel — partner accounts, contracts, price lists, per-order terms.

Design rules (see docs/design/b2b-supplier-module.md and ADR-0016):

- Everything here is ADDITIVE. No existing column changes meaning.
- ``Order.channel`` / ``Order.account_id`` are the only new columns on a
  core table, and both are nullable/defaulted so every existing row stays
  valid and every existing query keeps working.
- Prices live in ``b2b_price_items``, never on ``products.base_price``.
  Retail price stays retail price.
- A contract is versioned: editing prices means closing one contract and
  opening another, so an old order can never be repriced by history.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.order import Order
    from app.models.product import Product


class AccountKind(str, enum.Enum):
    """What kind of partner this is. Drives nothing but reporting today."""

    SHOP = "SHOP"
    FRANCHISEE = "FRANCHISEE"
    DISTRIBUTOR = "DISTRIBUTOR"


class PricingMode(str, enum.Enum):
    """How the partner's price is derived.

    UNIT_PRICE — an explicit per-product rate, from a price item or the
                 contract's fallback of the retail price.
    COMMISSION — the partner sells at MRP and keeps a commission; the
                 bakery invoices MRP minus that commission.
    """

    UNIT_PRICE = "UNIT_PRICE"
    COMMISSION = "COMMISSION"


class PaymentTerms(str, enum.Enum):
    ADVANCE = "ADVANCE"
    CREDIT = "CREDIT"
    COD = "COD"


class B2bAccount(Base):
    """A shop / franchisee the bakery supplies."""

    __tablename__ = "b2b_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[AccountKind] = mapped_column(
        SAEnum(AccountKind), nullable=False, default=AccountKind.SHOP
    )

    gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The billing contact. Orders require a customer_id (NOT NULL), so every
    # partner owns one Customer row created with it. Keeping that constraint
    # untouched is why this column exists.
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)

    # --- Standing commercial terms (a contract may override these) ---
    min_order_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    order_cutoff: Mapped[str] = mapped_column(String(5), nullable=False, default="18:00")
    lead_time_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    credit_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credit_limit: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    # ISO weekdays the partner accepts dispatch on, e.g. "1,2,3,4,5,6".
    dispatch_days: Mapped[str] = mapped_column(String(20), nullable=False, default="1,2,3,4,5,6")

    # --- Future switch: dedicated production line ---
    # Today a B2B order is baked on the same line as retail ("SHARED").
    # Setting this to "DEDICATED" is the hook for a separate batch/line
    # later; it is recorded per order so history stays readable either way.
    production_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="SHARED", server_default="SHARED"
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    customer: Mapped[Customer | None] = relationship(lazy="joined")
    contracts: Mapped[list[B2bContract]] = relationship(
        back_populates="account",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="B2bContract.effective_from.desc()",
    )

    __table_args__ = (
        Index(
            "uq_b2b_accounts_code_active",
            "code",
            unique=True,
            sqlite_where=text("is_active = 1"),
        ),
        Index("ix_b2b_accounts_is_active", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<B2bAccount id={self.id} code={self.code!r} name={self.name!r}>"

    @property
    def kind_label(self) -> str:
        return self.kind.value.replace("_", " ").title()

    @property
    def dispatch_weekdays(self) -> set[int]:
        out: set[int] = set()
        for part in (self.dispatch_days or "").split(","):
            part = part.strip()
            if part.isdigit() and 1 <= int(part) <= 7:
                out.add(int(part))
        return out or {1, 2, 3, 4, 5, 6}


class B2bContract(Base):
    """A versioned commercial agreement. Never mutate one that has orders."""

    __tablename__ = "b2b_contracts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("b2b_accounts.id"), nullable=False)

    label: Mapped[str] = mapped_column(String(100), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    pricing_mode: Mapped[PricingMode] = mapped_column(
        SAEnum(PricingMode), nullable=False, default=PricingMode.UNIT_PRICE
    )
    # Used when pricing_mode == COMMISSION and a product has no own commission.
    default_commission_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Optional overrides of the account's standing terms.
    min_order_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    credit_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    terms_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    account: Mapped[B2bAccount] = relationship(back_populates="contracts")
    price_items: Mapped[list[B2bPriceItem]] = relationship(
        back_populates="contract",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="B2bPriceItem.product_id, B2bPriceItem.min_qty",
    )

    __table_args__ = (Index("ix_b2b_contracts_account", "account_id", "effective_from"),)

    def __repr__(self) -> str:
        return f"<B2bContract id={self.id} account={self.account_id} {self.label!r}>"

    def covers(self, on_date: date) -> bool:
        if not self.is_active:
            return False
        if self.effective_from and on_date < self.effective_from:
            return False
        return not (self.effective_to and on_date > self.effective_to)

    @property
    def mode_label(self) -> str:
        return "Commission" if self.pricing_mode == PricingMode.COMMISSION else "Unit price"


class B2bPriceItem(Base):
    """One product, one quantity slab, one price OR one commission."""

    __tablename__ = "b2b_price_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("b2b_contracts.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)

    min_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Exactly one of these is set. unit_price wins when both are present.
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    commission_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    gst_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    contract: Mapped[B2bContract] = relationship(back_populates="price_items")
    product: Mapped[Product] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("contract_id", "product_id", "min_qty", name="uq_b2b_price_slab"),
        Index("ix_b2b_price_lookup", "contract_id", "product_id", "min_qty"),
    )

    def __repr__(self) -> str:
        return (
            f"<B2bPriceItem contract={self.contract_id} product={self.product_id} "
            f"qty>={self.min_qty}>"
        )


class B2bOrderTerms(Base):
    """Per-order B2B facts, snapshotted at creation. One row per B2B order."""

    __tablename__ = "b2b_order_terms"

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("b2b_accounts.id"), nullable=False)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("b2b_contracts.id"), nullable=True)

    po_reference: Mapped[str | None] = mapped_column(String(60), nullable=True)
    dispatch_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_terms: Mapped[PaymentTerms] = mapped_column(
        SAEnum(PaymentTerms), nullable=False, default=PaymentTerms.CREDIT
    )
    credit_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    production_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="SHARED", server_default="SHARED"
    )

    # Commercial checks that were true when the order was placed (min order
    # value, cut-off, credit limit...). Warnings only — a human decides.
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Resolved prices at creation, so a re-print never re-prices history.
    price_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    order: Mapped[Order] = relationship(back_populates="b2b_terms")
    account: Mapped[B2bAccount] = relationship(lazy="joined")

    __table_args__ = (Index("ix_b2b_order_terms_account", "account_id"),)

    def __repr__(self) -> str:
        return f"<B2bOrderTerms order={self.order_id} account={self.account_id}>"
