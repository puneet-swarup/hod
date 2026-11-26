"""Costing: recipes keyed to a family, packaging per size, and settings.

Why the recipe hangs off a *family* rather than a product row is recorded in
ADR 0018: this catalogue sells one brownie in five sizes, so a per-product
recipe would mean five copies of the same bill of materials and a sixth the
day a new box size appears.

``Product.family_key`` (normalised name) is the join. Nothing here stores a
product id for the recipe itself — only the packaging, which genuinely does
differ per size because a nine-piece box is not nine wrappers.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.time import utcnow


class Recipe(Base):
    """The bill of materials for one product family, expressed as a batch.

    ``yield_pieces`` is what makes sizes work: the lines describe one tray,
    and every size is that tray divided by its yield and multiplied by the
    pieces in the box.
    """

    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    #: Normalised product name — the same key Product.family_key produces.
    family_key: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Display name, so a recipe can be read without joining a product.
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    yield_pieces: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Minutes of work for the whole batch, not per piece.
    labour_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Electricity, gas, depreciation for one batch.
    overhead_per_batch: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    #: Spoilage and trim, as a percentage of material plus labour.
    wastage_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.00")
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    lines: Mapped[list[RecipeLine]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("family_key", name="uq_recipes_family_key"),
        Index("ix_recipes_family_key", "family_key"),
    )

    def __repr__(self) -> str:
        return f"<Recipe {self.family_key!r} yields {self.yield_pieces}>"


class RecipeLine(Base):
    """One ingredient in a batch recipe."""

    __tablename__ = "recipe_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False)

    #: In the ingredient's own unit — 1.2 kg of chocolate is 1200 g.
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    recipe: Mapped[Recipe] = relationship(back_populates="lines")
    ingredient: Mapped[Ingredient] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_recipe_lines_recipe", "recipe_id"),
        Index("ix_recipe_lines_ingredient", "ingredient_id"),
        UniqueConstraint("recipe_id", "ingredient_id", name="uq_recipe_line_ingredient"),
    )

    def __repr__(self) -> str:
        return f"<RecipeLine recipe={self.recipe_id} ingredient={self.ingredient_id}>"


class ProductPackaging(Base):
    """What one size of a product is packed in, and what that costs.

    Per product, not per recipe: packaging is the one cost that does not
    scale with the number of pieces.
    """

    __tablename__ = "product_packaging"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (Index("ix_product_packaging_product", "product_id"),)

    def __repr__(self) -> str:
        return f"<ProductPackaging product={self.product_id} {self.name!r}>"


class CostingSettings(Base):
    """The shop's costing assumptions — one row, edited from a screen.

    Kept in the database rather than a config file because these are
    business numbers the owner changes (a new labour rate), not deployment
    settings.
    """

    __tablename__ = "costing_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    labour_rate_per_hour: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("100.00")
    )
    default_wastage_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("5.00")
    )
    target_margin_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("40.00")
    )
    #: "exclusive" or "inclusive" — how the printed price relates to GST.
    gst_mode: Mapped[str] = mapped_column(String(12), nullable=False, default="exclusive")
    #: "none", "five" or "ten" — how a suggested price is rounded.
    price_rounding: Mapped[str] = mapped_column(String(12), nullable=False, default="five")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<CostingSettings labour={self.labour_rate_per_hour}/hr>"


# Imported at the bottom to avoid a circular import at module load: the
# relationships above are strings until SQLAlchemy configures the mappers.
from app.models.ingredient import Ingredient  # noqa: E402
