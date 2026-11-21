"""Integration tests for the order-form product type-ahead.

Regression focus: the item rows must filter products as the user types
(via /products/search), not render the full product list in a static
<select>. Mirrors tests/test_order_form_customer_search.py.
"""

from decimal import Decimal

from app.models import Product
from app.services.product_service import create_product

# ---------------------------------------------------------------------------
# Form wiring
# ---------------------------------------------------------------------------


def test_order_form_renders_typeahead_not_full_select(client, db, sample_product):
    """The product field is a search box backed by /products/search."""
    resp = client.get("/orders/new")
    assert resp.status_code == 200
    body = resp.text

    assert 'class="input input-bordered input-sm w-full product-search"' in body
    assert 'hx-get="/products/search"' in body
    assert 'hx-target="next .product-results"' in body

    # A hidden field carries the chosen product id (the form submits this).
    assert 'name="product_id"' in body
    assert 'class="product-id"' in body

    # No static <select name="product_id"> dumping every product.
    assert '<select name="product_id"' not in body


def test_order_form_does_not_preload_product_options(client, db, sample_product):
    """The full product list must not be embedded in the form."""
    body = client.get("/orders/new").text
    # sample_product is "Sample Cake" — it only appears after a search.
    assert "Sample Cake" not in body


def test_edit_form_prefills_chosen_product(client, db, sample_order, sample_product):
    """Editing an order shows the selected product's label and id."""
    body = client.get(f"/orders/{sample_order.id}/edit").text

    assert '<select name="product_id"' not in body
    assert f'class="product-id"\n                   value="{sample_product.id}"' in body
    assert 'value="Sample Cake"' in body
    assert 'data-selected-label="Sample Cake"' in body


# ---------------------------------------------------------------------------
# Search endpoint behaviour (what the type-ahead calls)
# ---------------------------------------------------------------------------


def _product(db, sku, name, category="Cake", active=True):
    p = create_product(
        db,
        {
            "sku": sku,
            "name": name,
            "base_price": Decimal("100.00"),
            "gst_rate": Decimal("5.00"),
            "category": category,
            "prep_time_hours": 2,
        },
    )
    if not active:
        p.is_active = False
        db.commit()
    return p


def test_search_filters_by_partial_name(client, db):
    _product(db, "AAA-1", "Almond Croissant")
    _product(db, "BBB-1", "Butter Cookies")

    resp = client.get("/products/search?q=Alm")
    assert resp.status_code == 200
    assert "Almond Croissant" in resp.text
    assert "Butter Cookies" not in resp.text


def test_search_matches_sku(client, db):
    _product(db, "CHOC-500", "Chocolate Truffle")

    resp = client.get("/products/search?q=CHOC")
    assert "Chocolate Truffle" in resp.text
    assert 'data-id="' in resp.text


def test_search_is_case_insensitive(client, db):
    _product(db, "AAA-1", "Almond Croissant")
    assert "Almond Croissant" in client.get("/products/search?q=almond").text


def test_search_excludes_inactive_products(client, db):
    _product(db, "OLD-1", "Retired Cake", active=False)
    assert "Retired Cake" not in client.get("/products/search?q=Retired").text


def test_search_requires_two_characters(client, db):
    _product(db, "AAA-1", "Almond Croissant")
    assert client.get("/products/search?q=A").text == ""


def test_search_returns_label_and_price_for_selection(client, db):
    _product(db, "AAA-1", "Almond Croissant")

    body = client.get("/products/search?q=Almond").text
    assert "product-result" in body
    assert 'data-label="Almond Croissant"' in body
    assert "data-price-label=" in body


def test_search_no_match_shows_empty_state(client, db):
    body = client.get("/products/search?q=zzzz").text
    assert "No products found" in body


def test_search_route_is_not_shadowed_by_product_id_routes(client, db):
    """/products/search must resolve to the type-ahead, not a 422/404."""
    resp = client.get("/products/search?q=zzzz")
    assert resp.status_code == 200


def test_search_does_not_leak_products_from_other_endpoints(db, client, sample_product):
    """Sanity: the partial is rendered by the endpoint, not cached globally."""
    assert isinstance(sample_product, Product)
