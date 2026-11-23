"""
ProductStockMovement — append-only ledger of finished goods.

Ingredients have a ledger (``StockMovement``); this is the same idea one
level up. Baking to stock, selling from stock, wastage and corrections are
rows here, and the quantity on hand is ``SUM(delta)``.

Why a ledger and not a number on the product:

- The owner can answer "how many do we have right now?" and "where did the
  other four go?" from the same table.
- A sale from stock is traceable to the order that took it, so an order can
  show "2 of 3 came from ready stock".
- Cancelling such an order puts the units back without anybody remembering
  to do it by hand.

Cost is recorded when the goods are BAKED (as ingredient consumption), not
when they are sold. A month that bakes a lot and sells little therefore
carries cost without matching revenue — see docs/design/BACKLOG.md.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.models.product import Product


class ProductMovementReason(str, enum.Enum):
    PRODUCTION = "PRODUCTION"  # baked or made into stock (+)
    SALE = "SALE"  # sold from stock, usually by an order (-)
    WASTAGE = "WASTAGE"  # spoiled, unsold, dropped (-)
    RETURN = "RETURN"  # back into stock after a cancelled order (+)
    ADJUSTMENT = "ADJUSTMENT"  # manual correction (+ or -)


class ProductStockMovement(Base):
    __tablename__ = "product_stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)

    # Positive = into stock, negative = out of stock.
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[ProductMovementReason] = mapped_column(
        SAEnum(ProductMovementReason), nullable=False
    )

    # What caused it, when it was not a manual action: "Order"/42.
    reference_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    product: Mapped[Product] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_product_stock_product", "product_id"),
        Index("ix_product_stock_created", "created_at"),
        Index("ix_product_stock_reference", "reference_type", "reference_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProductStockMovement product={self.product_id} "
            f"delta={self.delta} {self.reason.value}>"
        )
