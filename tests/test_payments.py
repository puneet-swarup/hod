"""Payment ledger tests — the axis independent of fulfillment.

Regression focus: an order may be DELIVERED (fulfillment terminal) while
still unpaid. The UI must never show a contradictory "PAID / Unpaid"
pair. Payment state is derived from the ledger, not the fulfillment enum.
"""

from decimal import Decimal

import pytest

from app.domain import DomainError
from app.models import OrderStatus
from app.services.order_service import create_order, record_payment, update_status

# ---------------------------------------------------------------------------
# payment_state derivation
# ---------------------------------------------------------------------------


def test_payment_state_unpaid_initially(db, customer, product):
    o = create_order(
        db,
        {
            "customer_id": customer.id,
            "fulfillment_date": "2026-12-31T12:00",
            "items": [{"product_id": product.id, "quantity": 1}],
            "advance_paid": 0,
        },
    )
    assert o.payment_state == "unpaid"
    assert o.payment_label == "Unpaid"


def test_payment_state_partial_after_advance(db, customer, product):
    o = create_order(
        db,
        {
            "customer_id": customer.id,
            "fulfillment_date": "2026-12-31T12:00",
            "items": [{"product_id": product.id, "quantity": 1}],
            "advance_paid": 10,
        },
    )
    assert o.payment_state == "partial"
    assert o.payment_label == "Partial"


def test_payment_state_paid_when_balance_zero(db, customer, product):
    o = create_order(
        db,
        {
            "customer_id": customer.id,
            "fulfillment_date": "2026-12-31T12:00",
            "items": [{"product_id": product.id, "quantity": 1}],
            "advance_paid": 0,
        },
    )
    record_payment(db, o.id, o.balance_due, "CASH", None)
    db.refresh(o)
    assert o.balance_due == Decimal("0.00")
    assert o.payment_state == "paid"
    assert o.payment_label == "Paid"


# ---------------------------------------------------------------------------
# Payment never changes fulfillment status
# ---------------------------------------------------------------------------


def test_full_payment_does_not_advance_status(db, customer, product):
    o = create_order(
        db,
        {
            "customer_id": customer.id,
            "fulfillment_date": "2026-12-31T12:00",
            "items": [{"product_id": product.id, "quantity": 1}],
            "advance_paid": 0,
        },
    )
    assert o.status == OrderStatus.CONFIRMED
    record_payment(db, o.id, o.balance_due, "UPI", None)
    db.refresh(o)
    assert o.status == OrderStatus.CONFIRMED


def test_delivered_can_be_unpaid(db, customer, product):
    """The core fix: DELIVERED + unpaid is a valid, non-contradictory state."""
    o = create_order(
        db,
        {
            "customer_id": customer.id,
            "fulfillment_date": "2026-12-31T12:00",
            "items": [{"product_id": product.id, "quantity": 1}],
            "advance_paid": 0,
        },
    )
    for status in ("IN_PROGRESS", "READY", "DELIVERED"):
        o = update_status(db, o.id, status)
    assert o.status == OrderStatus.DELIVERED
    assert o.payment_state == "unpaid"


def test_paid_status_is_not_a_fulfillment_state(db, customer, product):
    o = create_order(
        db,
        {
            "customer_id": customer.id,
            "fulfillment_date": "2026-12-31T12:00",
            "items": [{"product_id": product.id, "quantity": 1}],
        },
    )
    with pytest.raises(DomainError) as ei:
        update_status(db, o.id, "PAID")
    assert ei.value


# ---------------------------------------------------------------------------
# Payment validation
# ---------------------------------------------------------------------------


def test_overpayment_rejected(db, customer, product):
    o = create_order(
        db,
        {
            "customer_id": customer.id,
            "fulfillment_date": "2026-12-31T12:00",
            "items": [{"product_id": product.id, "quantity": 1}],
            "advance_paid": 0,
        },
    )
    with pytest.raises(DomainError) as ei:
        record_payment(db, o.id, o.balance_due + Decimal("1.00"), "CASH", None)
    assert ei.value


def test_payment_on_cancelled_rejected(db, customer, product):
    o = create_order(
        db,
        {
            "customer_id": customer.id,
            "fulfillment_date": "2026-12-31T12:00",
            "items": [{"product_id": product.id, "quantity": 1}],
        },
    )
    update_status(db, o.id, "CANCELLED")
    with pytest.raises(DomainError):
        record_payment(db, o.id, Decimal("1.00"), "CASH", None)


# ---------------------------------------------------------------------------
# Rendered list must not show a contradictory badge pair
# ---------------------------------------------------------------------------


def test_list_badge_pair_not_contradictory(client, db, customer, product):
    """A delivered-but-unpaid order must not render 'PAID' anywhere as a status."""
    o = create_order(
        db,
        {
            "customer_id": customer.id,
            "fulfillment_date": "2026-12-31T12:00",
            "items": [{"product_id": product.id, "quantity": 1}],
            "advance_paid": 0,
        },
    )
    for status in ("IN_PROGRESS", "READY", "DELIVERED"):
        update_status(db, o.id, status)

    resp = client.get("/orders")
    assert resp.status_code == 200
    body = resp.text
    # The fulfillment badge shows DELIVERED, never PAID.
    assert "DELIVERED" in body
    # The payment badge is explicitly labelled and reads Unpaid.
    assert "Payment: Unpaid" in body
