"""Ready stock — finished goods kept on the shelf for walk-in and ad-hoc orders.

The app's default flow is make-to-order: nothing is baked until an order
exists, and production is what consumes ingredients. This module adds the
other flow, which a home bakery actually runs in parallel:

    bake 10 brownies this morning  ->  ingredients down, 10 brownies ready
    someone walks in               ->  an order takes 2 from the shelf
    nobody buys the rest           ->  wastage, recorded, so it is visible

Everything is a ledger row, so the answer to "how many are ready?" is a SUM
and the answer to "where did they go?" is the rows themselves.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    MovementReason,
    Order,
    Product,
    ProductMovementReason,
    ProductStockMovement,
    StockMovement,
)
from app.services import inventory_service, recipe_service
from app.utils.money import money

# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def availability_map(db: Session, product_ids: list[int] | None = None) -> dict[int, int]:
    """{product_id: units on hand}. Absent means zero."""
    query = select(
        ProductStockMovement.product_id,
        func.coalesce(func.sum(ProductStockMovement.delta), 0),
    ).group_by(ProductStockMovement.product_id)
    if product_ids is not None:
        if not product_ids:
            return {}
        query = query.where(ProductStockMovement.product_id.in_(product_ids))
    return {pid: int(qty) for pid, qty in db.execute(query).all()}


def available(db: Session, product_id: int) -> int:
    total = db.execute(
        select(func.coalesce(func.sum(ProductStockMovement.delta), 0)).where(
            ProductStockMovement.product_id == product_id
        )
    ).scalar()
    return int(total or 0)


def movements_for(db: Session, product_id: int, limit: int = 50) -> list[ProductStockMovement]:
    return list(
        db.execute(
            select(ProductStockMovement)
            .where(ProductStockMovement.product_id == product_id)
            .order_by(ProductStockMovement.created_at.desc(), ProductStockMovement.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def drawn_for_order(db: Session, order_id: int) -> dict[int, int]:
    """{product_id: units this order took from ready stock}."""
    rows = db.execute(
        select(
            ProductStockMovement.product_id,
            func.coalesce(func.sum(ProductStockMovement.delta), 0),
        )
        .where(
            ProductStockMovement.reference_type == "Order",
            ProductStockMovement.reference_id == order_id,
        )
        .group_by(ProductStockMovement.product_id)
    ).all()
    # SALE rows are negative; report the positive quantity taken.
    return {pid: int(-qty) for pid, qty in rows if qty}


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _add(
    db: Session,
    product_id: int,
    delta: int,
    reason: ProductMovementReason,
    *,
    reference_type: str | None = None,
    reference_id: int | None = None,
    note: str | None = None,
    unit_cost: Decimal | None = None,
) -> ProductStockMovement:
    movement = ProductStockMovement(
        product_id=product_id,
        delta=delta,
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
        unit_cost=unit_cost,
    )
    db.add(movement)
    return movement


def average_cost(db: Session, product_id: int) -> Decimal:
    """Weighted-average cost of the units currently on the shelf.

    Computed from the ledger itself: what came in (production, returns) at
    its recorded cost, minus what went out at the cost it was released at.
    No separate running balance to drift out of step with the rows.
    """
    rows = db.execute(
        select(ProductStockMovement.delta, ProductStockMovement.unit_cost).where(
            ProductStockMovement.product_id == product_id
        )
    ).all()

    units = 0
    value = Decimal("0.00")
    last_cost: Decimal | None = None
    for delta, unit_cost in rows:
        if unit_cost is None:
            continue
        cost = Decimal(unit_cost)
        units += int(delta)
        value += cost * Decimal(delta)
        if delta > 0:
            last_cost = cost

    if units <= 0:
        return (last_cost or Decimal("0.00")).quantize(Decimal("0.01"))
    return (value / Decimal(units)).quantize(Decimal("0.01"))


def bake(db: Session, product_id: int, quantity: int, note: str | None = None) -> int:
    """Bake `quantity` units into ready stock. Returns the new on-hand count.

    Consumes ingredients through the recipe, exactly as producing for an
    order does — that is what keeps the ingredient ledger honest. A product
    with no recipe simply adds stock: the app cannot invent a bill of
    materials.
    """
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")

    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    unit_cost = recipe_service.recipe_cost(db, product_id).quantize(Decimal("0.01"))

    _add(
        db,
        product_id,
        quantity,
        ProductMovementReason.PRODUCTION,
        note=note or f"Baked {quantity} × {product.display_name}",
        unit_cost=unit_cost,
    )

    for line in recipe_service.list_recipe(db, product_id):
        used = line.quantity_per_unit * Decimal(quantity)
        if used <= 0:
            continue
        inventory_service.record_movement(
            db,
            line.ingredient_id,
            delta=-used,
            reason=MovementReason.CONSUMPTION,
            reference_type="Bake",
            reference_id=None,
            notes=f"Baked {quantity} × {product.display_name}",
            commit=False,
        )

    db.flush()
    return available(db, product_id)


def adjust(
    db: Session,
    product_id: int,
    delta: int,
    reason: ProductMovementReason,
    note: str | None = None,
) -> int:
    """Manual correction: wastage (-), a miscount (+/-), or a return (+)."""
    if delta == 0:
        raise HTTPException(status_code=400, detail="Nothing to adjust")
    if reason in {ProductMovementReason.PRODUCTION, ProductMovementReason.SALE}:
        raise HTTPException(
            status_code=400,
            detail="Use the bake or order flow for production and sales",
        )

    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    _add(
        db,
        product_id,
        delta,
        reason,
        note=note,
        unit_cost=average_cost(db, product_id) if delta < 0 else Decimal("0.00"),
    )
    db.flush()
    return available(db, product_id)


def draw_for_order(db: Session, order: Order) -> dict[int, int]:
    """Take what the order needs from ready stock, as far as it goes.

    Returns {product_id: quantity drawn}. Whatever is not covered here is
    made to order, and it is the made-to-order part that consumes
    ingredients.
    """
    drawn: dict[int, int] = {}
    on_hand = availability_map(db, [item.product_id for item in order.items])

    for item in order.items:
        left = on_hand.get(item.product_id, 0)
        if left <= 0:
            continue
        take = min(left, item.quantity)
        if take <= 0:
            continue
        _add(
            db,
            item.product_id,
            -take,
            ProductMovementReason.SALE,
            reference_type="Order",
            reference_id=order.id,
            note=f"{take} × {item.product.display_name if item.product else ''} "
            f"from ready stock for {order.order_number}",
            unit_cost=average_cost(db, item.product_id),
        )
        on_hand[item.product_id] = left - take
        drawn[item.product_id] = take

    db.flush()
    return drawn


def return_for_order(db: Session, order: Order) -> dict[int, int]:
    """Put back whatever this order took from ready stock (on cancel)."""
    taken = drawn_for_order(db, order.id)
    for product_id, qty in taken.items():
        if qty <= 0:
            continue
        _add(
            db,
            product_id,
            qty,
            ProductMovementReason.RETURN,
            reference_type="Order",
            reference_id=order.id,
            note=f"Returned to stock — {order.order_number} cancelled",
            unit_cost=average_cost(db, product_id),
        )
    db.flush()
    return taken


def stock_value(db: Session) -> dict:
    """Small summary for the screen header: units on hand, and what they cost."""
    rows = availability_map(db)
    on_shelf = {pid: qty for pid, qty in rows.items() if qty > 0}

    value = Decimal("0.00")
    for product_id, qty in on_shelf.items():
        value += average_cost(db, product_id) * Decimal(qty)

    return {
        "products_with_stock": len(on_shelf),
        "units": sum(on_shelf.values()),
        "value": money(value),
    }


def last_bake_at(db: Session, product_id: int):
    return db.execute(
        select(func.max(ProductStockMovement.created_at)).where(
            ProductStockMovement.product_id == product_id,
            ProductStockMovement.reason == ProductMovementReason.PRODUCTION,
        )
    ).scalar()


__all__ = [
    "availability_map",
    "available",
    "movements_for",
    "drawn_for_order",
    "bake",
    "adjust",
    "draw_for_order",
    "return_for_order",
    "stock_value",
    "last_bake_at",
    "StockMovement",
]
