"""B2B channel: accounts, contracts, pricing, orders, invoices, credit.

The behaviour pinned here is what makes the module safe to run next to
retail: retail prices never move, retail orders are untouched, and every
commercial check warns instead of blocking.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models import AccountKind, Order, OrderStatus, PricingMode
from app.services import b2b_service, invoice_service, order_service
from app.utils.time import business_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _account(db, code="SHOP-A", name="Sweet Corner", phone="9811100001", **extra):
    data = {
        "code": code,
        "name": name,
        "phone": phone,
        "kind": "SHOP",
        "min_order_value": "0",
        "credit_limit": "0",
        "credit_days": "0",
        "lead_time_hours": "0",
        "order_cutoff": "23:59",
        "dispatch_days": "1,2,3,4,5,6,7",
    }
    data.update(extra)
    return b2b_service.create_account(db, data)


def _contract(db, account, **extra):
    data = {
        "label": "Rates",
        "effective_from": (business_now().date() - timedelta(days=1)).isoformat(),
        "pricing_mode": "UNIT_PRICE",
    }
    data.update(extra)
    return b2b_service.create_contract(db, account.id, data)


def _b2b_order(db, account, product, qty=1, **extra):
    data = {
        "account_id": account.id,
        "items": [{"product_id": product.id, "quantity": qty}],
        "fulfillment_date": (business_now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
    }
    data.update(extra)
    return order_service.create_order(db, data)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def test_create_account_links_a_billing_customer(db):
    account = _account(db)
    assert account.id
    assert account.customer_id
    assert account.customer.name == "Sweet Corner"
    assert account.is_active is True
    assert account.production_mode == "SHARED"


def test_account_code_is_normalised_and_validated(db):
    account = _account(db, code=" shop-b ")
    assert account.code == "SHOP-B"

    with pytest.raises(HTTPException) as exc:
        _account(db, code="no spaces allowed", phone="9811100009")
    assert exc.value.status_code == 400


def test_duplicate_account_code_rejected(db):
    _account(db, code="DUP-1", phone="9811100002")
    with pytest.raises(HTTPException):
        _account(db, code="DUP-1", name="Other Shop", phone="9811100003")


def test_account_reuses_existing_customer_with_same_phone(db):
    from app.services.customer_service import create_customer

    existing = create_customer(
        db, {"name": "Priya", "phone": "9811100004", "email": None, "notes": ""}
    )
    account = _account(db, code="REUSE", phone="9811100004")
    assert account.customer_id == existing.id


def test_deactivate_is_soft(db):
    account = _account(db, code="SOFT-1")
    b2b_service.deactivate_account(db, account.id)
    assert account.is_active is False
    assert db.get(type(account), account.id) is not None


def test_dispatch_days_accepts_a_list(db):
    account = _account(db, code="DAYS-1", dispatch_days=["1", "3", "5"])
    assert account.dispatch_days == "1,3,5"
    assert account.dispatch_weekdays == {1, 3, 5}


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def test_no_contract_means_retail_price(db, product):
    account = _account(db, code="NORATE")
    resolved = b2b_service.resolve_price(db, account, product, 1)
    assert resolved["source"] == "RETAIL"
    assert resolved["unit_price"] == product.base_price


def test_contract_unit_price_wins(db, product):
    account = _account(db, code="RATE-1")
    contract = _contract(db, account)
    b2b_service.upsert_price_item(
        db, account.id, {"contract_id": contract.id, "product_id": product.id, "unit_price": "70.00"}
    )

    resolved = b2b_service.resolve_price(db, account, product, 1)
    assert resolved["source"] == "CONTRACT"
    assert resolved["unit_price"] == Decimal("70.00")
    # The retail price is untouched — this is the whole point.
    assert product.base_price == Decimal("99.99")


def test_quantity_slab_picks_the_best_match(db, product):
    account = _account(db, code="SLAB-1")
    contract = _contract(db, account)
    for min_qty, price in ((1, "80.00"), (10, "72.00"), (50, "65.00")):
        b2b_service.upsert_price_item(
            db,
            account.id,
            {
                "contract_id": contract.id,
                "product_id": product.id,
                "min_qty": min_qty,
                "unit_price": price,
            },
        )

    assert b2b_service.resolve_price(db, account, product, 1)["unit_price"] == Decimal("80.00")
    assert b2b_service.resolve_price(db, account, product, 9)["unit_price"] == Decimal("80.00")
    assert b2b_service.resolve_price(db, account, product, 10)["unit_price"] == Decimal("72.00")
    assert b2b_service.resolve_price(db, account, product, 200)["unit_price"] == Decimal("65.00")


def test_commission_mode_derives_the_price_from_mrp(db, product):
    account = _account(db, code="COMM-1")
    _contract(db, account, pricing_mode="COMMISSION", default_commission_pct="30")

    resolved = b2b_service.resolve_price(db, account, product, 1)
    assert resolved["source"] == "COMMISSION"
    # MRP 99.99 less 30% commission = 69.99
    assert resolved["unit_price"] == Decimal("69.99")


def test_per_product_commission_overrides_the_contract_default(db, product):
    account = _account(db, code="COMM-2")
    contract = _contract(db, account, pricing_mode="COMMISSION", default_commission_pct="20")
    b2b_service.upsert_price_item(
        db,
        account.id,
        {"contract_id": contract.id, "product_id": product.id, "commission_pct": "40"},
    )

    resolved = b2b_service.resolve_price(db, account, product, 1)
    assert resolved["unit_price"] == Decimal("59.99")  # 99.99 - 40%


def test_commission_contract_needs_a_default(db):
    account = _account(db, code="COMM-3")
    with pytest.raises(HTTPException):
        _contract(db, account, pricing_mode="COMMISSION")


def test_expired_contract_falls_back_to_retail(db, product):
    account = _account(db, code="OLD-1")
    contract = _contract(
        db,
        account,
        effective_from=(business_now().date() - timedelta(days=60)).isoformat(),
        effective_to=(business_now().date() - timedelta(days=30)).isoformat(),
    )
    b2b_service.upsert_price_item(
        db, account.id, {"contract_id": contract.id, "product_id": product.id, "unit_price": "50.00"}
    )

    assert b2b_service.resolve_price(db, account, product, 1)["source"] == "RETAIL"


def test_price_item_needs_a_price_or_a_commission(db):
    account = _account(db, code="EMPTY-1")
    contract = _contract(db, account)
    with pytest.raises(HTTPException):
        b2b_service.upsert_price_item(
            db, account.id, {"contract_id": contract.id, "product_id": 1, "min_qty": 1}
        )


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


def test_b2b_order_uses_contract_price_and_own_number_series(db, product):
    account = _account(db, code="ORD-1")
    contract = _contract(db, account)
    b2b_service.upsert_price_item(
        db, account.id, {"contract_id": contract.id, "product_id": product.id, "unit_price": "70.00"}
    )

    order = _b2b_order(db, account, product, qty=2)

    assert order.channel == "B2B"
    assert order.account_id == account.id
    assert order.order_number.startswith("HOD-B2B-")
    assert order.items[0].unit_price == Decimal("70.00")
    # 2 x 70 + 5% GST
    assert order.total_amount == Decimal("147.00")


def test_retail_order_is_unchanged_by_the_b2b_module(db, sample_customer, sample_product):
    order = order_service.create_order(
        db,
        {
            "customer_id": sample_customer.id,
            "items": [{"product_id": sample_product.id, "quantity": 1}],
            "fulfillment_date": (business_now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
        },
    )
    assert order.channel == "RETAIL"
    assert order.account_id is None
    assert order.order_number.startswith("HOD-") and "-B2B-" not in order.order_number
    assert order.items[0].unit_price == sample_product.base_price
    assert order.b2b_terms is None


def test_b2b_order_records_po_reference_and_terms(db, product):
    account = _account(db, code="ORD-2", credit_days="15")
    order = _b2b_order(
        db, account, product, po_reference="PO-778", payment_terms="CREDIT", dispatch_date="2026-12-01"
    )

    terms = order.b2b_terms
    assert terms is not None
    assert terms.po_reference == "PO-778"
    assert terms.credit_days == 15
    assert terms.dispatch_date == date(2026, 12, 1)
    assert terms.production_mode == "SHARED"


def test_advance_terms_zero_out_the_credit_days(db, product):
    account = _account(db, code="ORD-3", credit_days="30")
    order = _b2b_order(db, account, product, payment_terms="ADVANCE")
    assert order.b2b_terms.credit_days == 0


def test_b2b_order_below_minimum_warns_but_saves(db, product):
    account = _account(db, code="MIN-1", min_order_value="5000")
    order = _b2b_order(db, account, product, qty=1)

    import json

    warnings = json.loads(order.b2b_terms.warnings_json)
    assert any("minimum order" in w for w in warnings)
    assert order.status == OrderStatus.CONFIRMED  # not blocked


def test_credit_limit_warns_but_saves(db, product):
    account = _account(db, code="CRED-1", credit_limit="100")
    order = _b2b_order(db, account, product, qty=5)

    import json

    warnings = json.loads(order.b2b_terms.warnings_json)
    assert any("Credit limit" in w for w in warnings)
    assert order.status == OrderStatus.CONFIRMED


def test_outstanding_is_the_sum_of_unpaid_b2b_balances(db, product):
    account = _account(db, code="OUT-1")
    first = _b2b_order(db, account, product, qty=1)
    _b2b_order(db, account, product, qty=2)

    assert b2b_service.outstanding(db, account.id) == first.total_amount + Decimal("209.98")


def test_cancelled_order_leaves_outstanding(db, product):
    account = _account(db, code="OUT-2")
    order = _b2b_order(db, account, product, qty=1)
    order_service.update_status(db, order.id, "CANCELLED")
    assert b2b_service.outstanding(db, account.id) == Decimal("0.00")


def test_inactive_account_cannot_take_an_order(db, product):
    account = _account(db, code="DEAD-1")
    b2b_service.deactivate_account(db, account.id)
    with pytest.raises(HTTPException):
        _b2b_order(db, account, product)


def test_editing_a_b2b_order_reprices_from_the_contract(db, product):
    account = _account(db, code="EDIT-1")
    contract = _contract(db, account)
    b2b_service.upsert_price_item(
        db, account.id, {"contract_id": contract.id, "product_id": product.id, "unit_price": "70.00"}
    )
    order = _b2b_order(db, account, product, qty=1)

    updated = order_service.update_order(
        db,
        order.id,
        {
            "items": [{"product_id": product.id, "quantity": 4}],
            "fulfillment_date": (business_now() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M"),
            "delivery_type": "PICKUP",
        },
    )
    assert updated.items[0].quantity == 4
    assert updated.total_amount == Decimal("294.00")


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


def test_invoice_carries_partner_gstin_and_po(db, product):
    account = _account(db, code="INV-1", gstin="27ABCDE1234F1Z5")
    order = _b2b_order(db, account, product, po_reference="PO-42")

    invoice = invoice_service.create_invoice(db, order.id)
    assert invoice.billed_to_name == "Sweet Corner"
    assert invoice.billed_to_gstin == "27ABCDE1234F1Z5"
    assert invoice.po_reference == "PO-42"


def test_retail_invoice_has_no_gstin_or_po(db, sample_order):
    invoice = invoice_service.create_invoice(db, sample_order.id)
    assert invoice.billed_to_gstin == ""
    assert invoice.po_reference == ""


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------


def test_partners_list_page_loads(client, db):
    _account(db, code="HTTP-1")
    resp = client.get("/b2b/")
    assert resp.status_code == 200
    assert "Sweet Corner" in resp.text


def test_create_partner_via_form(client, db):
    resp = client.post(
        "/b2b/",
        data={
            "name": "Form Shop",
            "code": "FORM-1",
            "kind": "SHOP",
            "phone": "9811100100",
            "min_order_value": "0",
            "order_cutoff": "18:00",
            "lead_time_hours": "24",
            "credit_days": "0",
            "credit_limit": "0",
            "dispatch_days": ["1", "2"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    from app.models import B2bAccount

    assert db.query(B2bAccount).filter(B2bAccount.code == "FORM-1").count() == 1


def test_partner_detail_shows_price_list(client, db, product):
    account = _account(db, code="HTTP-2")
    contract = _contract(db, account)
    b2b_service.upsert_price_item(
        db, account.id, {"contract_id": contract.id, "product_id": product.id, "unit_price": "70.00"}
    )

    resp = client.get(f"/b2b/{account.id}")
    assert resp.status_code == 200
    assert "Chocolate Truffle 500g" in resp.text
    assert "70.00" in resp.text


def test_quote_endpoint_prices_a_basket(client, db, product):
    account = _account(db, code="QUOTE-1", min_order_value="5000")
    contract = _contract(db, account)
    b2b_service.upsert_price_item(
        db, account.id, {"contract_id": contract.id, "product_id": product.id, "unit_price": "70.00"}
    )

    resp = client.get(f"/b2b/{account.id}/quote?items={product.id}:2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["lines"][0]["unit_price"] == "70.00"
    assert body["lines"][0]["source"] == "CONTRACT"
    assert body["total"] == "147.00"
    assert any("minimum order" in w for w in body["warnings"])


def test_quote_endpoint_handles_an_empty_basket(client, db):
    account = _account(db, code="QUOTE-2")
    body = client.get(f"/b2b/{account.id}/quote?items=").json()
    assert body["lines"] == []
    assert body["total"] == "0.00"


def test_partner_search_partial(client, db):
    _account(db, code="FIND-1", name="Bandra Bakes", phone="9811100200")
    body = client.get("/b2b/search?q=bandra").text
    assert "Bandra Bakes" in body
    assert 'class="partner-result"' in body or "partner-result" in body


def test_statement_csv_download(client, db, product):
    account = _account(db, code="STATE-1")
    _b2b_order(db, account, product, qty=1)

    resp = client.get(f"/b2b/{account.id}/statement.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "STATE-1" in resp.text


def test_order_form_offers_the_partner_mode(client, db):
    body = client.get("/orders/new").text
    assert 'data-channel="B2B"' in body
    assert 'hx-get="/b2b/search"' in body
    assert 'name="account_id"' in body


def test_order_form_preselects_a_partner(client, db):
    account = _account(db, code="PRE-1")
    body = client.get(f"/orders/new?account_id={account.id}").text
    assert 'id="channel" value="B2B"' in body
    assert 'id="account_id"' in body and str(account.id) in body


def test_create_b2b_order_over_http(client, db, product):
    account = _account(db, code="HTTP-3")
    contract = _contract(db, account)
    b2b_service.upsert_price_item(
        db, account.id, {"contract_id": contract.id, "product_id": product.id, "unit_price": "70.00"}
    )

    resp = client.post(
        "/orders/",
        data={
            "customer_id": str(account.customer_id),
            "channel": "B2B",
            "account_id": str(account.id),
            "po_reference": "PO-9",
            "payment_terms": "CREDIT",
            "delivery_type": "PICKUP",
            "fulfillment_date": (business_now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            "product_id": [str(product.id)],
            "quantity": ["2"],
            "advance_paid": "0",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    order = db.query(Order).filter(Order.channel == "B2B").one()
    assert order.account_id == account.id
    assert order.b2b_terms.po_reference == "PO-9"
    assert order.total_amount == Decimal("147.00")


def test_b2b_order_without_a_partner_is_rejected(client, db, product, sample_customer):
    resp = client.post(
        "/orders/",
        data={
            "customer_id": str(sample_customer.id),
            "channel": "B2B",
            "account_id": "",
            "delivery_type": "PICKUP",
            "fulfillment_date": (business_now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            "product_id": [str(product.id)],
            "quantity": ["1"],
        },
    )
    assert resp.status_code == 400
    assert "B2B partner" in resp.text


# ---------------------------------------------------------------------------
# Data preservation
# ---------------------------------------------------------------------------


def test_existing_orders_default_to_retail_channel(db, sample_order):
    db.refresh(sample_order)
    assert sample_order.channel == "RETAIL"
    assert sample_order.account_id is None


def test_order_date_is_local_not_utc(db, sample_customer, sample_product):
    """order_date is the business calendar date; it must not flip after 18:30 IST."""
    order = order_service.create_order(
        db,
        {
            "customer_id": sample_customer.id,
            "items": [{"product_id": sample_product.id, "quantity": 1}],
            "fulfillment_date": (business_now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
        },
    )
    assert order.order_date.date() == business_now().date()
