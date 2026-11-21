"""Order and OrderItem models."""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.models.b2b import B2bAccount, B2bOrderTerms
    from app.models.customer import Customer
    from app.models.payment import Payment
    from app.models.product import Product


class OrderStatus(str, enum.Enum):
    INQUIRY = "INQUIRY"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# Fulfillment workflow only. The terminal states are DELIVERED (success)
# and CANCELLED (failure). Whether the customer has paid is a SEPARATE
# axis, tracked by Order.payment_state and the payment ledger. Payments
# never change fulfillment status, and fulfillment never encodes payment.
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.INQUIRY: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED},
    OrderStatus.IN_PROGRESS: {OrderStatus.READY, OrderStatus.CANCELLED},
    OrderStatus.READY: {OrderStatus.DELIVERED, OrderStatus.CANCELLED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)

    # Sales channel. 'RETAIL' for every order that existed before the B2B
    # module; 'B2B' when a partner account is attached. Defaulted in the
    # database too, so an old row is valid the moment the column appears.
    channel: Mapped[str] = mapped_column(
        String(10), nullable=False, default="RETAIL", server_default="RETAIL"
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("b2b_accounts.id"), nullable=True
    )

    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus), nullable=False, default=OrderStatus.INQUIRY
    )

    order_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    fulfillment_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivery_type: Mapped[str] = mapped_column(String(10), nullable=False, default="PICKUP")
    delivery_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    advance_paid: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    balance_due: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    customer: Mapped[Customer] = relationship(back_populates="orders", lazy="joined")
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="OrderItem.id",
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="order",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="Payment.received_at",
    )
    account: Mapped[B2bAccount | None] = relationship(lazy="joined")
    b2b_terms: Mapped[B2bOrderTerms | None] = relationship(
        back_populates="order",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_orders_status", "status"),
        Index("ix_orders_created_at", "created_at"),
        Index("ix_orders_customer_id", "customer_id"),
        Index("ix_orders_order_date", "order_date"),
        Index("ix_orders_fulfillment_date", "fulfillment_date"),
        Index("ix_orders_channel", "channel"),
        Index("ix_orders_account_id", "account_id"),
    )

    # ---------- Computed helpers ----------

    @property
    def is_b2b(self) -> bool:
        return self.channel == "B2B"

    @property
    def channel_label(self) -> str:
        return {"RETAIL": "Retail", "B2B": "B2B", "QR": "QR"}.get(self.channel, self.channel)

    @property
    def partner_name(self) -> str | None:
        """The shop this order is for, when it is a B2B order."""
        return self.account.name if self.account else None

    @property
    def payment_state(self) -> str:
        """Independent of fulfillment status. 'paid' / 'partial' / 'unpaid'."""
        if self.balance_due is not None and self.balance_due <= 0:
            return "paid"
        if self.advance_paid is not None and self.advance_paid > 0:
            return "partial"
        return "unpaid"

    @property
    def payment_badge_class(self) -> str:
        return {
            "paid": "badge-success",
            "partial": "badge-warning",
            "unpaid": "badge-ghost",
        }[self.payment_state]

    @property
    def payment_label(self) -> str:
        return {
            "paid": "Paid",
            "partial": "Partial",
            "unpaid": "Unpaid",
        }[self.payment_state]

    @property
    def status_badge_class(self) -> str:
        return {
            "INQUIRY": "badge-ghost",
            "CONFIRMED": "badge-info",
            "IN_PROGRESS": "badge-warning",
            "DELIVERED": "badge-success",
            "PAID": "badge-success",
            "CANCELLED": "badge-error",
        }.get(self.status.value, "badge-ghost")

    @property
    def allowed_next_statuses(self) -> list[OrderStatus]:
        """The legal next statuses from the current one, sorted."""
        return sorted(
            ALLOWED_TRANSITIONS.get(self.status, set()),
            key=lambda s: s.value,
        )

    def can_transition_to(self, new_status: OrderStatus) -> bool:
        return new_status in ALLOWED_TRANSITIONS.get(self.status, set())

    def __repr__(self) -> str:
        return f"<Order id={self.id} number={self.order_number!r} status={self.status}>"


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)

    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("5.00")
    )
    gst_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )

    customization_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_order_items_order_id", "order_id"),
        Index("ix_order_items_product_id", "product_id"),
    )

    def __repr__(self) -> str:
        return f"<OrderItem id={self.id} product_id={self.product_id} qty={self.quantity}>"
