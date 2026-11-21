"""Integration tests for the order-form customer typeahead.

Regression focus: the order form must filter customers as the user types
(via /customers/search), not render the full customer list in a static
<select>. These tests render the real form HTML and exercise the search
endpoint the form points at.
"""

from app.models import Customer

# ---------------------------------------------------------------------------
# Form wiring
# ---------------------------------------------------------------------------


def test_order_form_renders_typeahead_not_full_select(client, db, sample_customer):
    """The customer field is a search box backed by /customers/search."""
    resp = client.get("/orders/new")
    assert resp.status_code == 200
    body = resp.text

    # The typeahead input exists and is wired to the search endpoint.
    assert 'id="customer-search"' in body
    assert 'hx-get="/customers/search"' in body
    assert 'hx-target="#customer-results"' in body

    # A hidden field carries the selected customer id (the form submits this).
    assert 'name="customer_id"' in body
    assert 'id="customer_id"' in body

    # No static <select name="customer_id"> dumping every customer.
    assert '<select name="customer_id"' not in body


def test_order_form_does_not_preload_customer_options(client, db, sample_customer):
    """The full customer list must not be embedded in the form."""
    resp = client.get("/orders/new")
    body = resp.text
    # sample_customer is "Test Customer" — it must not appear as a preselected
    # option in the initial form (it only appears after a search).
    assert "Test Customer" not in body


# ---------------------------------------------------------------------------
# Search endpoint behaviour (what the typeahead calls)
# ---------------------------------------------------------------------------


def test_search_filters_by_partial_name(client, db):
    db.add_all(
        [
            Customer(name="Anita Rao", phone="9000000001", is_active=True),
            Customer(name="Bharat Kumar", phone="9000000002", is_active=True),
        ]
    )
    db.commit()

    resp = client.get("/customers/search?q=Ani")
    assert resp.status_code == 200
    assert "Anita Rao" in resp.text
    assert "Bharat Kumar" not in resp.text


def test_search_requires_two_chars(client, db):
    db.add(Customer(name="Anita Rao", phone="9000000001", is_active=True))
    db.commit()

    resp = client.get("/customers/search?q=A")
    assert resp.status_code == 200
    assert "Anita Rao" not in resp.text


def test_search_filters_by_phone(client, db):
    db.add_all(
        [
            Customer(name="Anita Rao", phone="9111122222", is_active=True),
            Customer(name="Bharat Kumar", phone="9333344444", is_active=True),
        ]
    )
    db.commit()

    resp = client.get("/customers/search?q=11112")
    assert resp.status_code == 200
    assert "Anita Rao" in resp.text
    assert "Bharat Kumar" not in resp.text


def test_search_excludes_inactive(client, db):
    db.add(
        Customer(name="Gone Away", phone="9000000009", is_active=False),
    )
    db.commit()
    resp = client.get("/customers/search?q=Gone")
    assert resp.status_code == 200
    assert "Gone Away" not in resp.text


def test_search_result_rows_carry_selection_data(client, db, sample_customer):
    """Each result row exposes the data the JS needs to select + autofill."""
    resp = client.get("/customers/search?q=Test")
    body = resp.text
    assert "customer-result" in body
    assert 'data-id="' in body
    assert 'data-name="Test Customer"' in body
    assert "data-addr-lines" in body


# ---------------------------------------------------------------------------
# End-to-end: the id captured by the typeahead is accepted by POST /orders
# ---------------------------------------------------------------------------


def test_order_creates_with_customer_id_from_search(client, db, sample_customer, sample_product):
    """Simulate the JS flow: search -> pick id -> submit order."""
    search = client.get("/customers/search?q=Test")
    assert str(sample_customer.id) in search.text

    resp = client.post(
        "/orders",
        data={
            "customer_id": str(sample_customer.id),
            "fulfillment_date": "2026-12-31T12:00",
            "delivery_type": "PICKUP",
            "delivery_address": "",
            "notes": "",
            "advance_paid": "0",
            "advance_method": "UPI",
            "product_id": [str(sample_product.id)],
            "quantity": ["1"],
        },
        follow_redirects=True,
    )
    # Lands on the order detail page after the redirect.
    assert resp.status_code == 200
    assert "Payments" in resp.text
