"""The costing service: loading, saving and auditing around the calculator.

The arithmetic is not tested here — it lives in ``app/domain/costing.py`` and
is covered to 100% without a database. What is tested here is the part that
can only be wrong with storage: which recipe a product resolves to, what
happens when it has none, and that a bad input is refused before anything is
written.
"""

from decimal import Decimal

import pytest

from app.domain import NotFoundError, ValidationError
from app.models import CostingSettings, ProductPackaging, Recipe
from app.services import costing_service as cs

D = Decimal


def _ingredient(db, name, cost, unit="g"):
    from app.models import Ingredient, IngredientKind

    ing = Ingredient(
        name=name,
        unit=unit,
        kind=IngredientKind.RAW,
        cost_per_unit=D(cost),
        reorder_threshold=D("0"),
        is_active=True,
    )
    db.add(ing)
    db.flush()
    return ing


def _family(db, name="Nutella Brownie", price="1170", pack_size=9):
    """Two sizes of one product family, the shape the catalogue really has."""
    from app.services import product_service

    big = product_service.create_product(
        db,
        {
            "name": name,
            "base_price": D(price),
            "gst_rate": 5,
            "category": "Brownie",
            "pack_size": pack_size,
            "pack_label": "",
            "prep_time_hours": 4,
            "is_active": True,
        },
    )
    small = product_service.create_product(
        db,
        {
            "name": name,
            "base_price": D("150"),
            "gst_rate": 5,
            "category": "Brownie",
            "pack_size": 1,
            "pack_label": "",
            "prep_time_hours": 4,
            "is_active": True,
        },
    )
    return big, small


def _recipe(db, family_key, lines, **kw):
    return cs.save_recipe(
        db,
        family_key=family_key,
        name=family_key.title(),
        yield_pieces=kw.pop("yield_pieces", 24),
        labour_minutes=kw.pop("labour_minutes", 90),
        overhead_per_batch=kw.pop("overhead_per_batch", "120"),
        wastage_pct=kw.pop("wastage_pct", "5"),
        lines=lines,
        **kw,
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_are_created_with_defaults_on_first_use(db):
    settings = cs.get_settings(db)
    assert settings.labour_rate_per_hour == D("100.00")
    assert settings.target_margin_pct == D("40.00")
    # Called twice, still one row.
    assert cs.get_settings(db).id == settings.id
    assert db.query(CostingSettings).count() == 1


def test_settings_can_be_changed(db):
    cs.update_settings(db, {"labour_rate_per_hour": "150", "target_margin_pct": "35"})
    db.expire_all()
    settings = cs.get_settings(db)
    assert settings.labour_rate_per_hour == D("150.00")
    assert settings.target_margin_pct == D("35.00")


@pytest.mark.parametrize(
    "payload",
    [
        {"labour_rate_per_hour": "-1"},
        {"default_wastage_pct": "100"},
        {"target_margin_pct": "120"},
    ],
)
def test_nonsense_settings_are_refused(db, payload):
    with pytest.raises(ValidationError):
        cs.update_settings(db, payload)


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------


def test_a_recipe_is_saved_with_its_lines(db):
    flour = _ingredient(db, "Maida", "0.04")
    butter = _ingredient(db, "Butter", "0.55")

    recipe = _recipe(
        db,
        "nutella brownie",
        [
            {"ingredient_id": flour.id, "quantity": "300"},
            {"ingredient_id": butter.id, "quantity": "800"},
        ],
    )

    assert recipe.id is not None
    assert len(recipe.lines) == 2
    assert recipe.yield_pieces == 24


def test_saving_twice_replaces_rather_than_duplicates(db):
    flour = _ingredient(db, "Maida", "0.04")
    _recipe(db, "nutella brownie", [{"ingredient_id": flour.id, "quantity": "300"}])
    _recipe(db, "nutella brownie", [{"ingredient_id": flour.id, "quantity": "500"}])

    assert db.query(Recipe).count() == 1
    recipe = cs.recipe_for(db, "nutella brownie")
    assert len(recipe.lines) == 1
    assert recipe.lines[0].quantity == D("500.000")


def test_a_recipe_needs_a_yield(db):
    with pytest.raises(ValidationError):
        cs.save_recipe(db, family_key="x", name="X", yield_pieces=0)


def test_the_same_ingredient_twice_is_refused(db):
    flour = _ingredient(db, "Maida", "0.04")
    with pytest.raises(ValidationError) as exc:
        _recipe(
            db,
            "nutella brownie",
            [
                {"ingredient_id": flour.id, "quantity": "300"},
                {"ingredient_id": flour.id, "quantity": "200"},
            ],
        )
    assert exc.value.context["ingredient_id"] == flour.id


def test_an_inactive_ingredient_is_refused(db):
    from app.services import inventory_service

    flour = _ingredient(db, "Old Flour", "0.04")
    inventory_service.delete_ingredient(db, flour.id)

    with pytest.raises(ValidationError):
        _recipe(db, "nutella brownie", [{"ingredient_id": flour.id, "quantity": "300"}])


def test_a_zero_quantity_line_is_refused(db):
    flour = _ingredient(db, "Maida", "0.04")
    with pytest.raises(ValidationError):
        _recipe(db, "nutella brownie", [{"ingredient_id": flour.id, "quantity": "0"}])


# ---------------------------------------------------------------------------
# Cost of a product
# ---------------------------------------------------------------------------


def test_an_uncosted_family_returns_none_not_zero(db):
    """None means 'not costed yet'. Zero would read as a 100% margin."""
    big, _ = _family(db)
    assert cs.cost_for(db, big) is None
    assert cs.cost_sheet(db, big)["costed"] is False


def test_every_size_of_a_family_costs_from_one_recipe(db):
    """The point of ADR 0018: one bill of materials, five sizes."""
    flour = _ingredient(db, "Maida", "0.10")
    big, small = _family(db)
    _recipe(db, big.family_key, [{"ingredient_id": flour.id, "quantity": "240"}])

    big_cost = cs.cost_for(db, big)
    small_cost = cs.cost_for(db, small)

    assert big_cost is not None and small_cost is not None
    # 240 g over 24 pieces = 10 g a piece = ₹1.00; nine pieces = ₹9.00
    assert big_cost.material == D("9.00")
    assert small_cost.material == D("1.00")


def test_packaging_is_charged_once_per_item_not_per_piece(db):
    flour = _ingredient(db, "Maida", "0.10")
    big, _ = _family(db)
    _recipe(db, big.family_key, [{"ingredient_id": flour.id, "quantity": "240"}])
    cs.set_packaging(db, big.id, "9-pc box", "35")

    cost = cs.cost_for(db, big)
    assert cost.packaging == D("35.00")


def test_the_settings_rate_reaches_the_calculation(db):
    flour = _ingredient(db, "Maida", "0.10")
    big, _ = _family(db)
    _recipe(db, big.family_key, [{"ingredient_id": flour.id, "quantity": "240"}], labour_minutes=60)

    cs.update_settings(db, {"labour_rate_per_hour": "60"})
    cost = cs.cost_for(db, big)
    # 60 minutes at ₹60/hr, scaled from 24 pieces to 9.
    assert cost.labour == D("22.50")


def test_the_sheet_reports_margin_and_a_suggested_price(db):
    flour = _ingredient(db, "Maida", "0.10")
    big, _ = _family(db)
    _recipe(db, big.family_key, [{"ingredient_id": flour.id, "quantity": "240"}])

    sheet = cs.cost_sheet(db, big)

    assert sheet["costed"] is True
    assert sheet["price"] == D("1170.00")
    assert sheet["margin"] == sheet["breakdown"].margin_at(D("1170"))
    assert sheet["suggested_price"] > 0


def test_packaging_is_listed_for_the_screen(db):
    big, _ = _family(db)
    cs.set_packaging(db, big.id, "9-pc box", "35")
    rows = cs.packaging_for(db, big.id)
    assert len(rows) == 1
    assert rows[0].name == "9-pc box"


def test_packaging_for_a_missing_product_is_refused(db):
    with pytest.raises(NotFoundError):
        cs.set_packaging(db, 999_999, "box", "10")


def test_negative_packaging_is_refused(db):
    big, _ = _family(db)
    with pytest.raises(ValidationError):
        cs.set_packaging(db, big.id, "box", "-5")


def test_deleting_a_recipe_that_does_not_exist_is_not_found(db):
    with pytest.raises(NotFoundError):
        cs.delete_recipe(db, "nothing here")


def test_a_recipe_can_be_deleted(db):
    flour = _ingredient(db, "Maida", "0.10")
    big, _ = _family(db)
    _recipe(db, big.family_key, [{"ingredient_id": flour.id, "quantity": "240"}])

    cs.delete_recipe(db, big.family_key)
    assert cs.recipe_for(db, big.family_key) is None
    assert db.query(Recipe).count() == 0


def test_the_recipe_reaches_the_right_family_only(db):
    """A brownie recipe must not cost a cookie."""
    flour = _ingredient(db, "Maida", "0.10")
    brownie, _ = _family(db, name="Nutella Brownie")
    cookie, _ = _family(db, name="Nutella Cookies")
    _recipe(db, brownie.family_key, [{"ingredient_id": flour.id, "quantity": "240"}])

    assert cs.cost_for(db, brownie) is not None
    assert cs.cost_for(db, cookie) is None


def test_packaging_rows_exist_independently_of_a_recipe(db):
    big, _ = _family(db)
    cs.set_packaging(db, big.id, "9-pc box", "35")
    assert db.query(ProductPackaging).count() == 1
    # Still uncosted: packaging alone does not make a recipe.
    assert cs.cost_for(db, big) is None


# ---------------------------------------------------------------------------
# The screens
# ---------------------------------------------------------------------------


def test_the_costing_index_lists_families_and_flags_the_uncosted(client, db):
    flour = _ingredient(db, "Maida", "0.10")
    big, _ = _family(db, name="Nutella Brownie")
    _family(db, name="Ginger Cookie", price="200")
    _recipe(db, big.family_key, [{"ingredient_id": flour.id, "quantity": "240"}])
    db.commit()

    body = client.get("/costing/").text
    assert "Nutella Brownie" in body
    assert "Ginger Cookie" in body
    assert "no recipe yet" in body


def test_the_sheet_shows_the_breakdown(client, db):
    flour = _ingredient(db, "Maida", "0.10")
    big, _ = _family(db)
    _recipe(db, big.family_key, [{"ingredient_id": flour.id, "quantity": "240"}])
    db.commit()

    body = client.get(f"/costing/{big.id}").text
    assert "Total cost" in body
    assert "Gross margin" in body


def test_the_sheet_invites_a_recipe_when_there_is_none(client, db):
    big, _ = _family(db)
    db.commit()

    body = client.get(f"/costing/{big.id}").text
    assert "No recipe for this family yet" in body
    assert "unknown, not zero" in body


def test_a_recipe_can_be_saved_from_the_screen(client, db):
    flour = _ingredient(db, "Maida", "0.10")
    big, _ = _family(db)
    db.commit()

    resp = client.post(
        f"/costing/{big.id}/recipe",
        data={
            "yield_pieces": "24",
            "labour_minutes": "90",
            "overhead_per_batch": "120",
            "wastage_pct": "5",
            "ingredient_id": [str(flour.id)],
            "quantity": ["240"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert cs.recipe_for(db, big.family_key) is not None


def test_packaging_can_be_set_from_the_screen(client, db):
    big, _ = _family(db)
    db.commit()

    resp = client.post(
        f"/costing/{big.id}/packaging",
        data={"name": "9-pc box", "cost": "35"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert len(cs.packaging_for(db, big.id)) == 1


def test_assumptions_can_be_saved_from_the_screen(client, db):
    resp = client.post(
        "/costing/settings",
        data={"labour_rate_per_hour": "175", "target_margin_pct": "45"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert cs.get_settings(db).labour_rate_per_hour == D("175.00")


# ---------------------------------------------------------------------------
# M12 — pricing, and the only route that changes a price
# ---------------------------------------------------------------------------


def test_three_ways_to_price_the_same_product(db):
    flour = _ingredient(db, "Maida", "0.10")
    big, _ = _family(db)
    _recipe(db, big.family_key, [{"ingredient_id": flour.id, "quantity": "240"}])

    suggestions = cs.suggest_prices(db, big)
    assert [s.method for s in suggestions] == ["margin", "markup", "market"]
    # The market price is what the product already charges.
    assert suggestions[2].price == big.base_price


def test_an_uncosted_product_has_no_suggestion(db):
    big, _ = _family(db)
    assert cs.suggest_prices(db, big) == []


def test_applying_a_price_records_the_change(db):
    from app.models import AuditLog

    big, _ = _family(db)
    cs.apply_price(db, big, "1300")

    assert big.base_price == D("1300.00")
    entry = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "Product", AuditLog.action == "PRICE_CHANGE")
        .first()
    )
    assert entry is not None
    assert "1170" in entry.old_value
    assert "1300" in entry.new_value


def test_a_price_of_zero_is_refused(db):
    big, _ = _family(db)
    with pytest.raises(ValidationError):
        cs.apply_price(db, big, "0")


def test_the_price_can_be_applied_from_the_screen(client, db):
    big, _ = _family(db)
    db.commit()

    resp = client.post(
        f"/costing/{big.id}/price", data={"price": "1275"}, follow_redirects=False
    )
    assert resp.status_code == 303
    db.expire_all()
    assert db.get(type(big), big.id).base_price == D("1275.00")


# ---------------------------------------------------------------------------
# M13 — bulk entry
# ---------------------------------------------------------------------------


def test_the_bulk_entry_page_renders(client, db):
    body = client.get("/costing/import").text
    assert "Ingredients" in body and "Recipes" in body


def test_ingredients_can_be_pasted_in(client, db):
    rows = "Dark chocolate, g, 0.45\nButter, g, 0.55\n\nSugar, g, 0.045\n"
    resp = client.post(
        "/costing/import/ingredients", data={"rows": rows}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert db.query(type(_ingredient(db, "x", "1"))).count() >= 4


def test_a_bad_ingredient_line_imports_nothing(client, db):
    from app.models import Ingredient

    rows = "Butter, g, 0.55\nSugar, g, free\n"
    resp = client.post("/costing/import/ingredients", data={"rows": rows})
    assert resp.status_code == 400
    assert "not a number" in resp.text
    assert db.query(Ingredient).count() == 0


def test_a_whole_recipe_can_be_pasted_in(client, db):
    for name, cost in (("Dark chocolate", "0.45"), ("Butter", "0.55")):
        _ingredient(db, name, cost)
    db.commit()

    rows = "Nutella Brownie, Dark chocolate, 1200, 24\nNutella Brownie, Butter, 800, 24\n"
    resp = client.post("/costing/import/recipes", data={"rows": rows}, follow_redirects=False)

    assert resp.status_code == 303
    recipe = cs.recipe_for(db, "nutella brownie")
    assert recipe is not None
    assert recipe.yield_pieces == 24
    assert len(recipe.lines) == 2


def test_a_recipe_naming_an_unknown_ingredient_imports_nothing(client, db):
    from app.models import Recipe

    _ingredient(db, "Butter", "0.55")
    db.commit()

    rows = "Nutella Brownie, Butter, 800, 24\nNutella Brownie, Unicorn tears, 10, 24\n"
    resp = client.post("/costing/import/recipes", data={"rows": rows})

    assert resp.status_code == 400
    assert "Unicorn tears" in resp.text
    assert db.query(Recipe).count() == 0


def test_the_yield_defaults_when_it_is_left_off(client, db):
    _ingredient(db, "Butter", "0.55")
    db.commit()

    client.post(
        "/costing/import/recipes",
        data={"rows": "Ginger Cookie, Butter, 100\n"},
        follow_redirects=False,
    )
    assert cs.recipe_for(db, "ginger cookie").yield_pieces == 24


# ---------------------------------------------------------------------------
# Discoverability — a screen nobody can reach is not a feature
# ---------------------------------------------------------------------------


def test_the_navigation_links_to_costing(client, db):
    """The module shipped with screens and no way in. This keeps the door open."""
    body = client.get("/today").text
    assert 'href="/costing"' in body


def test_the_navigation_links_to_ready_stock(client, db):
    body = client.get("/today").text
    assert 'href="/stock"' in body


def test_no_button_class_inside_the_more_menu():
    """The menu is a list of plain links; a .btn inside it centres itself and
    breaks the column, which is exactly how the Ready-stock entry drifted out
    of alignment."""
    import pathlib
    import re

    html = pathlib.Path("app/templates/base.html").read_text(encoding="utf-8")
    menu = re.search(r'<div class="nav-more-menu">(.*?)</div>', html, re.S)
    assert menu, "the More menu should still exist"
    assert "btn " not in menu.group(1), (
        "Use a plain <a> inside .nav-more-menu — a button class breaks the "
        "alignment column"
    )
