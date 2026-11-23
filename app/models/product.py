"""Product model — a sellable item."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.time import utcnow


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="Cake")

    # One product per SELLABLE unit, but products that share a name are one
    # family: "Nutella Brownie" in 4 pc / 9 pc / 12 pc / 1 kg. variant_label
    # is the size that distinguishes them ("9 pc"), so the picker can show
    # "Nutella Brownie · 9 pc — ₹540" instead of five identical rows.
    variant_label: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Weight or volume — optional. measure_value is meaningless without measure_unit.
    measure_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    measure_unit: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Pack of N units in one SKU. Default 1 = single item.
    pack_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    pack_label: Mapped[str] = mapped_column(String(50), nullable=False, default="")

    base_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("5.00")
    )
    prep_time_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=4)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        Index(
            "uq_products_sku_active",
            "sku",
            unique=True,
            sqlite_where=text("is_active = 1"),
        ),
        Index("ix_products_is_active", "is_active"),
        Index("ix_products_category", "category"),
    )

    @property
    def family_key(self) -> str:
        """Products sharing this are sizes of the same thing."""
        return " ".join((self.name or "").lower().split())

    @property
    def size_label(self) -> str:
        """What distinguishes this product from its siblings, best first."""
        if self.variant_label:
            return self.variant_label
        if self.pack_label:
            return self.pack_label
        measure = self.measure_display
        if measure:
            return measure
        if self.pack_size and self.pack_size > 1:
            return f"Pack of {self.pack_size}"
        return ""

    @property
    def display_name(self) -> str:
        """'Nutella Brownie · 9 pc' — used everywhere a product is listed."""
        size = self.size_label
        return f"{self.name} · {size}" if size else self.name

    @property
    def measure_display(self) -> str:
        """Human-readable measure, e.g. '500 g' or '1 kg' or '' if unset."""
        if self.measure_value is None or not self.measure_unit:
            return ""
        v = self.measure_value.normalize()
        if v == v.to_integral_value():
            v = v.quantize(Decimal("1"))
        return f"{v} {self.measure_unit}"

    @property
    def pack_display(self) -> str:
        """Human-readable pack, e.g. 'Pack of 6' or '' if single."""
        if self.pack_label:
            return self.pack_label
        if self.pack_size and self.pack_size > 1:
            return f"Pack of {self.pack_size}"
        return ""

    def __repr__(self) -> str:
        return f"<Product id={self.id} sku={self.sku!r} name={self.name!r}>"
