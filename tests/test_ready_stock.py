"""Ready stock: baking ahead of orders, and selling from the shelf.

The two flows have to coexist without double-counting ingredients. An order
that takes two brownies off the shelf must not consume their flour again —
that flour went when they were baked.
"""

from datetime import timedelta
from decimal import Decimal

from app.models import Ingredient, IngredientKind, MovementReason, ProductMovementReason
from app.services import inventory_service, order_service, ready_stock_service, recipe_service
from app.utils.time import business_now


def _ingredient(db, name="Flour", unit="g", cost="0.06"):
    ing = Ingredient(
        name=name,
        unit=unit,
        kind=IngredientKind.RAW,
        cost_per_unit=Decimal(cost),
        reorder_threshold=Decimal("0"),
        is_active=True,
    )
    db.add(ing)
    db.flush()
    inventory_service.record_movement(
        db,
        ing.id,
        delta=Decimal("10000"),
        reason=MovementReason.PURCHASE,
        notes="opening",
        commit=False,
    )
    db.commit()
    return ing


def _recipe(db, product, ingredient, per_unit="100"):
    recipe_service.upsert_recipe_line(db, product.id, ingredient.id, Decimal(per_unit))
    db.commit()


def _order(db, customer, product, qty=1):
    return order_service.create_order(
        db,
        {
            "customer_id": customer.id,
            "items": [{"product_id": product.id, "quantity": qty}],
            "fulfillment_date": (business_now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
        },
    )


# ---------------------------------------------------------------------------
# Baking into stock
# ---------------------------------------------------------------------------


def test_baking_puts_units_on_the_shelf(db, sample_product):
    assert ready_stock_service.available(db, sample_product.id) == 0

    ready_stock_service.bake(db, sample_product.id, 10)
    db.commit()

    assert ready_stock_service.available(db, sample_product.id) == 10


def test_baking_consumes_ingredients_through_the_recipe(db, sample_product):
    flour = _ingredient(db)
    _recipe(db, sample_product, flour, per_unit="100")
    before = inventory_service.on_hand(db, flour.id)

    ready_stock_service.bake(db, sample_product.id, 3)
    db.commit()

    # 3 units × 100 g
    assert inventory_service.on_hand(db, flour.id) == before - Decimal("300")


def test_baking_without_a_recipe_still_adds_stock(db, sample_product):
    ready_stock_service.bake(db, sample_product.id, 2)
    db.commit()
    assert ready_stock_service.available(db, sample_product.id) == 2


def test_baking_zero_or_negative_is_refused(db, sample_product):
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        ready_stock_service.bake(db, sample_product.id, 0)


# ---------------------------------------------------------------------------
# Selling from the shelf
# ---------------------------------------------------------------------------


def test_an_order_takes_from_the_shelf_before_baking(db, sample_customer, sample_product):
    flour = _ingredient(db)
    _recipe(db, sample_product, flour, per_unit="100")
    ready_stock_service.bake(db, sample_product.id, 5)
    db.commit()

    flour_before = inventory_service.on_hand(db, flour.id)
    order = _order(db, sample_customer, sample_product, qty=2)
    order_service.update_status(db, order.id, "IN_PROGRESS")

    assert ready_stock_service.available(db, sample_product.id) == 3
    # The two from the shelf consumed no new flour.
    assert inventory_service.on_hand(db, flour.id) == flour_before
    assert ready_stock_service.drawn_for_order(db, order.id) == {sample_product.id: 2}


def test_only_the_shortfall_is_baked_to_order(db, sample_customer, sample_product):
    flour = _ingredient(db)
    _recipe(db, sample_product, flour, per_unit="100")
    ready_stock_service.bake(db, sample_product.id, 1)
    db.commit()

    flour_before = inventory_service.on_hand(db, flour.id)
    order = _order(db, sample_customer, sample_product, qty=3)
    order_service.update_status(db, order.id, "IN_PROGRESS")

    assert ready_stock_service.available(db, sample_product.id) == 0
    # 1 from stock, 2 made to order → 200 g of flour.
    assert inventory_service.on_hand(db, flour.id) == flour_before - Decimal("200")


def test_cancelling_puts_the_shelf_units_back(db, sample_customer, sample_product):
    ready_stock_service.bake(db, sample_product.id, 4)
    db.commit()

    order = _order(db, sample_customer, sample_product, qty=2)
    order_service.update_status(db, order.id, "IN_PROGRESS")
    assert ready_stock_service.available(db, sample_product.id) == 2

    order_service.update_status(db, order.id, "CANCELLED", salvage=True)
    assert ready_stock_service.available(db, sample_product.id) == 4


def test_wastage_reduces_the_shelf(db, sample_product):
    ready_stock_service.bake(db, sample_product.id, 5)
    db.commit()

    ready_stock_service.adjust(
        db, sample_product.id, -2, ProductMovementReason.WASTAGE, "unsold"
    )
    db.commit()

    assert ready_stock_service.available(db, sample_product.id) == 3


# ---------------------------------------------------------------------------
# The screen the owner actually uses
# ---------------------------------------------------------------------------


def test_the_availability_screen_shows_what_is_ready(client, db, sample_product):
    ready_stock_service.bake(db, sample_product.id, 7)
    db.commit()

    body = client.get("/stock/").text
    assert "Ready stock" in body
    assert sample_product.name in body
    assert ">7<" in body or "7\n" in body


def test_baking_from_the_screen_works(client, db, sample_product):
    resp = client.post(
        "/stock/bake",
        data={"product_id": sample_product.id, "quantity": 3, "note": "morning batch"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert ready_stock_service.available(db, sample_product.id) == 3


def test_the_order_picker_shows_what_is_ready(client, db, sample_product):
    ready_stock_service.bake(db, sample_product.id, 4)
    db.commit()

    body = client.get("/products/search", params={"q": sample_product.name}).text
    assert "4 ready" in body
