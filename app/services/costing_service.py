"""Costing service — the database side of the calculator.

Everything here is loading, saving and auditing. **No arithmetic** happens in
this module: the numbers come from ``app.domain.costing``, which is pure and
100% covered. That split is the point — a bug in the maths is found by a
test that needs no database, and a bug in the loading is found here.

The service raises domain errors, never HTTP (see ENGINEERING_STANDARDS.md).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import NotFoundError, ValidationError
from app.domain.costing import CostBreakdown, CostLine, calculate
from app.domain.pricing import PriceSuggestion, by_margin, by_market, by_markup
from app.models import CostingSettings, Ingredient, Product, ProductPackaging, Recipe, RecipeLine
from app.services.audit_service import log_action

# ---------------------------------------------------------------------------
# Settings — one row, edited from a screen
# ---------------------------------------------------------------------------


def get_settings(db: Session) -> CostingSettings:
    """The shop's costing assumptions, created with defaults on first use."""
    settings = db.execute(select(CostingSettings).limit(1)).scalars().first()
    if settings is None:
        settings = CostingSettings()
        db.add(settings)
        db.flush()
    return settings


def update_settings(db: Session, data: dict) -> CostingSettings:
    """Change the assumptions. Validated before anything is written."""
    settings = get_settings(db)

    rate = data.get("labour_rate_per_hour")
    if rate not in (None, ""):
        rate_d = Decimal(str(rate))
        if rate_d < 0:
            raise ValidationError("Labour rate cannot be negative", value=str(rate))
        settings.labour_rate_per_hour = rate_d

    wastage = data.get("default_wastage_pct")
    if wastage not in (None, ""):
        wastage_d = Decimal(str(wastage))
        if not (Decimal(0) <= wastage_d < 100):
            raise ValidationError("Wastage must be between 0 and 100 percent", value=str(wastage))
        settings.default_wastage_pct = wastage_d

    margin = data.get("target_margin_pct")
    if margin not in (None, ""):
        margin_d = Decimal(str(margin))
        if not (Decimal(0) <= margin_d < 100):
            raise ValidationError("Target margin must be between 0 and 100 percent", value=str(margin))
        settings.target_margin_pct = margin_d

    if data.get("gst_mode") in {"exclusive", "inclusive"}:
        settings.gst_mode = data["gst_mode"]
    if data.get("price_rounding") in {"none", "five", "ten"}:
        settings.price_rounding = data["price_rounding"]

    log_action(
        db,
        entity_type="CostingSettings",
        entity_id=settings.id,
        action="UPDATE",
        new_value={
            "labour_rate_per_hour": str(settings.labour_rate_per_hour),
            "default_wastage_pct": str(settings.default_wastage_pct),
            "target_margin_pct": str(settings.target_margin_pct),
        },
    )
    db.flush()
    return settings


# ---------------------------------------------------------------------------
# Recipes — one per family (ADR 0018)
# ---------------------------------------------------------------------------


def recipe_for(db: Session, family_key: str) -> Recipe | None:
    """The active recipe for a family, or None if it has not been costed."""
    return (
        db.execute(
            select(Recipe).where(Recipe.family_key == family_key, Recipe.is_active.is_(True))
        )
        .scalars()
        .first()
    )


def list_recipes(db: Session) -> list[Recipe]:
    return list(db.execute(select(Recipe).order_by(Recipe.name)).scalars().all())


def save_recipe(
    db: Session,
    *,
    family_key: str,
    name: str,
    yield_pieces: int,
    labour_minutes: int = 0,
    overhead_per_batch: Decimal | str = 0,
    wastage_pct: Decimal | str = 0,
    notes: str | None = None,
    lines: list[dict] | None = None,
) -> Recipe:
    """Create or replace the recipe for a family, including its lines.

    Replacing is deliberate: a half-updated bill of materials would cost
    the wrong thing silently, which is worse than losing the old one.
    """
    if not family_key.strip():
        raise ValidationError("A recipe needs a family")
    if int(yield_pieces) <= 0:
        raise ValidationError("A batch must yield at least one piece", value=str(yield_pieces))

    overhead = Decimal(str(overhead_per_batch or 0))
    wastage = Decimal(str(wastage_pct or 0))
    if overhead < 0:
        raise ValidationError("Overhead cannot be negative", value=str(overhead))
    if not (Decimal(0) <= wastage < 100):
        raise ValidationError("Wastage must be between 0 and 100 percent", value=str(wastage))

    recipe = recipe_for(db, family_key)
    if recipe is None:
        recipe = Recipe(family_key=family_key.strip(), name=name.strip() or family_key)
        db.add(recipe)
        db.flush()
    else:
        recipe.name = name.strip() or recipe.name

    recipe.yield_pieces = int(yield_pieces)
    recipe.labour_minutes = int(labour_minutes or 0)
    recipe.overhead_per_batch = overhead
    recipe.wastage_pct = wastage
    recipe.notes = notes or None

    if lines is not None:
        # Clear through the relationship, not with individual deletes: the
        # cascade removes the rows and the in-memory collection stays in
        # step, so a caller can read back what it just wrote.
        recipe.lines.clear()
        db.flush()

        seen: set[int] = set()
        for row in lines:
            ingredient_id = int(row["ingredient_id"])
            if ingredient_id in seen:
                raise ValidationError(
                    f"Ingredient {ingredient_id} listed twice", ingredient_id=ingredient_id
                )
            seen.add(ingredient_id)

            ingredient = db.get(Ingredient, ingredient_id)
            if ingredient is None or not ingredient.is_active:
                raise ValidationError(
                    f"Ingredient {ingredient_id} not found or inactive",
                    ingredient_id=ingredient_id,
                )

            quantity = Decimal(str(row["quantity"]))
            if quantity <= 0:
                raise ValidationError(
                    "A recipe line needs a positive quantity", ingredient_id=ingredient_id
                )
            recipe.lines.append(
                RecipeLine(
                    ingredient_id=ingredient_id,
                    quantity=quantity,
                    notes=(row.get("notes") or None),
                )
            )

    log_action(
        db,
        entity_type="Recipe",
        entity_id=recipe.id,
        action="UPSERT",
        new_value={
            "family_key": recipe.family_key,
            "yield_pieces": recipe.yield_pieces,
            "lines": len(recipe.lines),
        },
    )
    db.flush()
    return recipe


def delete_recipe(db: Session, family_key: str) -> None:
    recipe = recipe_for(db, family_key)
    if recipe is None:
        raise NotFoundError(entity="Recipe")
    log_action(
        db,
        entity_type="Recipe",
        entity_id=recipe.id,
        action="DELETE",
        old_value={"family_key": recipe.family_key},
    )
    db.delete(recipe)
    db.flush()


# ---------------------------------------------------------------------------
# Packaging — per product, because it does not scale with pieces
# ---------------------------------------------------------------------------


def packaging_for(db: Session, product_id: int) -> list[ProductPackaging]:
    return list(
        db.execute(
            select(ProductPackaging)
            .where(ProductPackaging.product_id == product_id)
            .order_by(ProductPackaging.is_default.desc(), ProductPackaging.name)
        )
        .scalars()
        .all()
    )


def set_packaging(db: Session, product_id: int, name: str, cost: Decimal | str) -> ProductPackaging:
    """Add or update the packaging for one size of a product."""
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError(entity="Product")

    cost_d = Decimal(str(cost or 0))
    if cost_d < 0:
        raise ValidationError("Packaging cost cannot be negative", value=str(cost))
    if not name.strip():
        raise ValidationError("Packaging needs a name")

    existing = (
        db.execute(
            select(ProductPackaging).where(
                ProductPackaging.product_id == product_id,
                ProductPackaging.name == name.strip(),
            )
        )
        .scalars()
        .first()
    )
    if existing is None:
        existing = ProductPackaging(product_id=product_id, name=name.strip(), cost=cost_d)
        db.add(existing)
    else:
        existing.cost = cost_d

    db.flush()
    return existing


# ---------------------------------------------------------------------------
# The cost of a product
# ---------------------------------------------------------------------------


def cost_for(db: Session, product: Product) -> CostBreakdown | None:
    """The cost of one sellable size, or None when the family has no recipe.

    None is meaningful: it means "not costed yet", which the screen shows as
    an invitation to enter the recipe rather than as a cost of zero. A zero
    would read as a 100% margin, which is a lie.
    """
    recipe = recipe_for(db, product.family_key)
    if recipe is None:
        return None

    settings = get_settings(db)

    material = [
        CostLine(
            label=f"{line.ingredient.name} {line.quantity:g} {line.ingredient.unit}",
            quantity=line.quantity,
            unit_cost=line.ingredient.cost_per_unit or Decimal("0"),
        )
        for line in recipe.lines
        if line.ingredient is not None
    ]

    packaging_rows = [p for p in packaging_for(db, product.id) if p.is_default][:1]
    packaging = [
        CostLine(label=row.name, quantity=Decimal(1), unit_cost=row.cost)
        for row in packaging_rows
    ]

    return calculate(
        material=material,
        packaging=packaging,
        pieces=max(int(product.pack_size or 1), 1),
        yield_pieces=recipe.yield_pieces,
        labour_minutes=recipe.labour_minutes,
        labour_rate_per_hour=settings.labour_rate_per_hour,
        overhead_per_batch=recipe.overhead_per_batch,
        wastage_pct=recipe.wastage_pct,
    )


def cost_sheet(db: Session, product: Product) -> dict:
    """Everything the cost sheet screen needs, in one call.

    Returns ``costed=False`` when there is no recipe, so the template can
    invite the owner to add one instead of rendering a zero.
    """
    settings = get_settings(db)
    recipe = recipe_for(db, product.family_key)
    breakdown = cost_for(db, product) if recipe else None
    packaging = packaging_for(db, product.id)

    sheet: dict = {
        "product": product,
        "recipe": recipe,
        "packaging": packaging,
        "settings": settings,
        "breakdown": breakdown,
        "costed": breakdown is not None,
        "price": product.base_price or Decimal("0.00"),
        "gst_rate": product.gst_rate or Decimal("0"),
    }

    if breakdown is not None:
        price = Decimal(product.base_price or 0)
        sheet.update(
            {
                "margin": breakdown.margin_at(price),
                "margin_pct": breakdown.margin_pct_at(price),
                "markup_pct": breakdown.markup_pct_at(price),
                "suggested_price": breakdown.price_for_margin(settings.target_margin_pct),
                "break_even": breakdown.break_even(),
                "suggestions": suggest_prices(db, product),
            }
        )

    return sheet


def suggest_prices(db: Session, product: Product) -> list[PriceSuggestion]:
    """The three ways to price this product, side by side.

    All three are returned rather than one, because they answer different
    questions and a baker uses all three at different times. An empty list
    means the family is not costed yet.
    """
    breakdown = cost_for(db, product)
    if breakdown is None:
        return []

    settings = get_settings(db)
    gst_rate = product.gst_rate or Decimal("0")

    return [
        by_margin(
            breakdown,
            settings.target_margin_pct,
            rounding=settings.price_rounding,
            gst_rate=gst_rate,
        ),
        by_markup(breakdown, Decimal("50"), rounding=settings.price_rounding, gst_rate=gst_rate),
        by_market(breakdown, product.base_price or Decimal("0"), gst_rate=gst_rate),
    ]


def apply_price(db: Session, product: Product, price: Decimal | str) -> Product:
    """Set a product's selling price, and record who changed it and from what.

    The only place a price moves. Nothing in this module ever calls it on its
    own: a suggestion becomes a price because a person pressed a button.
    """
    new_price = Decimal(str(price))
    if new_price <= 0:
        raise ValidationError("A selling price must be greater than zero", value=str(price))

    old_price = product.base_price
    product.base_price = new_price.quantize(Decimal("0.01"))

    log_action(
        db,
        entity_type="Product",
        entity_id=product.id,
        action="PRICE_CHANGE",
        old_value={"base_price": str(old_price)},
        new_value={"base_price": str(product.base_price)},
    )
    db.flush()
    return product


__all__ = [
    "get_settings",
    "update_settings",
    "recipe_for",
    "list_recipes",
    "save_recipe",
    "delete_recipe",
    "packaging_for",
    "set_packaging",
    "cost_for",
    "cost_sheet",
    "suggest_prices",
    "apply_price",
]
