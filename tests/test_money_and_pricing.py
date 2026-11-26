"""Money that moves: price overrides, cancellations, and cash vs accrual.

Three behaviours the bakery relies on:

1. A product sold above or below its configured price keeps BOTH numbers,
   so the difference is visible rather than silently replacing the list.
2. Cancelling an order clears the balance it can no longer collect, and
   keeps the cash that was actually taken.
3. The monthly report distinguishes revenue (earned) from cash (received)
   and carries a bridge that always closes — because a month-end order paid
   the next month is normal, not an error.
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain import DomainError
from app.services import order_service, reports_service
from app.utils.time import business_now


def _order(db, customer, product, qty=1, price=None, advance=0, order_date=None):
    item = {"product_id": product.id, "quantity": qty}
    if price is not None:
        item["unit_price"] = str(price)
    data = {
        "customer_id": customer.id,
        "items": [item],
        "fulfillment_date": (business_now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
        "advance_paid": Decimal(str(advance)),
    }
    if order_date:
        data["order_date"] = order_date
    return order_service.create_order(db, data)


# ---------------------------------------------------------------------------
# Price above / below list
# ---------------------------------------------------------------------------


def test_selling_above_list_keeps_both_prices(db, sample_customer, sample_product):
    """sample_product lists at 500. Charge 750 for a festival box."""
    order = _order(db, sample_customer, sample_product, price=750)

    item = order.items[0]
    assert item.unit_price == Decimal("750.00")
    assert item.list_price == Decimal("500.00")
    assert item.price_delta == Decimal("250.00")
    assert item.price_note == "above list"
    # The line total follows what was charged, GST included.
    assert item.line_total == Decimal("787.50")


def test_selling_below_list_is_recorded_too(db, sample_customer, sample_product):
    order = _order(db, sample_customer, sample_product, price=400)
    item = order.items[0]
    assert item.price_delta == Decimal("-100.00")
    assert item.price_note == "below list"


def test_no_override_means_list_price(db, sample_customer, sample_product):
    order = _order(db, sample_customer, sample_product)
    item = order.items[0]
    assert item.unit_price == item.list_price == Decimal("500.00")
    assert item.price_delta == Decimal("0.00")
    assert item.price_note == ""


def test_a_price_of_zero_is_refused(db, sample_customer, sample_product):
    with pytest.raises(DomainError) as exc:
        _order(db, sample_customer, sample_product, price=0)
    assert exc.value


def test_a_nonsense_price_is_refused(db, sample_customer, sample_product):
    with pytest.raises(DomainError) as exc:
        _order(db, sample_customer, sample_product, price="not a number")
    assert exc.value


def test_the_report_lists_what_was_sold_away_from_list(db, sample_customer, sample_product):
    _order(db, sample_customer, sample_product, qty=2, price=750)
    now = business_now()
    report = reports_service.build_report(db, now.year, now.month)

    assert len(report["price_adjustments"]) == 1
    row = report["price_adjustments"][0]
    assert row["list_price"] == Decimal("500.00")
    assert row["charged"] == Decimal("750.00")
    assert row["delta_total"] == Decimal("500.00")  # 250 × 2
    assert report["price_adjustment_total"] == Decimal("500.00")


# ---------------------------------------------------------------------------
# Cancellation and the money it leaves behind
# ---------------------------------------------------------------------------


def test_cancelling_clears_the_balance_and_keeps_the_cash(db, sample_customer, sample_product):
    order = _order(db, sample_customer, sample_product, advance=200)
    assert order.balance_due == Decimal("325.00")  # 525 − 200

    order_service.update_status(db, order.id, "CANCELLED")
    db.refresh(order)

    assert order.status.value == "CANCELLED"
    assert order.balance_due == Decimal("0.00")  # cannot be owed
    assert order.advance_paid == Decimal("200.00")  # cash was still taken


def test_the_report_shows_money_held_on_cancelled_orders(db, sample_customer, sample_product):
    order = _order(db, sample_customer, sample_product, advance=200)
    order_service.update_status(db, order.id, "CANCELLED")

    now = business_now()
    report = reports_service.build_report(db, now.year, now.month)

    # Not revenue, and not cash received on live business…
    assert report["total_revenue"] == Decimal("0.00")
    assert report["cash_received"] == Decimal("0.00")
    # …but it is not lost either.
    assert report["cash_held_cancelled"] == Decimal("200.00")
    assert report["held_on_cancelled_total"] == Decimal("200.00")


# ---------------------------------------------------------------------------
# Cash vs accrual — the "these never match" question
# ---------------------------------------------------------------------------


def test_a_payment_in_a_later_month_is_cash_then_not_revenue(db, sample_customer, sample_product):
    """Order placed last month, paid this month — the month-end case."""
    now = business_now()
    prev_month_last_day = now.replace(day=1) - timedelta(days=1)

    order = _order(
        db,
        sample_customer,
        sample_product,
        order_date=prev_month_last_day.strftime("%Y-%m-%d"),
    )
    # Paid now, in the current month.
    order_service.record_payment(db, order.id, Decimal("525.00"), "UPI", "TEST-1")

    this_month = reports_service.build_report(db, now.year, now.month)
    last_month = reports_service.build_report(
        db, prev_month_last_day.year, prev_month_last_day.month
    )

    # Revenue belongs to the month it was earned in.
    assert last_month["total_revenue"] == Decimal("525.00")
    assert this_month["total_revenue"] == Decimal("0.00")

    # Cash belongs to the month it arrived in.
    assert this_month["cash_received"] == Decimal("525.00")
    assert last_month["cash_received"] == Decimal("0.00")

    # And both months still explain themselves.
    assert last_month["closing_outstanding"] == Decimal("525.00")
    assert this_month["closing_outstanding"] == Decimal("0.00")


def test_the_bridge_always_closes(db, sample_customer, sample_product):
    now = business_now()
    prev_month_last_day = now.replace(day=1) - timedelta(days=1)

    # One order from last month, partly paid this month.
    old = _order(
        db,
        sample_customer,
        sample_product,
        order_date=prev_month_last_day.strftime("%Y-%m-%d"),
    )
    order_service.record_payment(db, old.id, Decimal("100.00"), "CASH", None)

    # One order this month, partly paid.
    _order(db, sample_customer, sample_product, advance=50)

    report = reports_service.build_report(db, now.year, now.month)

    assert report["closing_outstanding"] == (
        report["opening_outstanding"] + report["total_revenue"] - report["cash_received"]
    )

    # …and it equals what the books actually say is owed on live orders.
    from sqlalchemy import func, select

    from app.models import Order, OrderStatus

    owed = db.execute(
        select(func.coalesce(func.sum(Order.balance_due), 0)).where(
            Order.status != OrderStatus.CANCELLED
        )
    ).scalar()
    assert report["closing_outstanding"] == Decimal(str(owed))


def test_cancelled_money_is_outside_the_bridge(db, sample_customer, sample_product):
    """Cash held on a cancelled order must not disturb the reconciliation."""
    order = _order(db, sample_customer, sample_product, advance=200)
    order_service.update_status(db, order.id, "CANCELLED")
    _order(db, sample_customer, sample_product)  # a normal unpaid order

    now = business_now()
    report = reports_service.build_report(db, now.year, now.month)

    assert report["cash_received"] == Decimal("0.00")
    assert report["cash_held_cancelled"] == Decimal("200.00")
    assert report["closing_outstanding"] == report["opening_outstanding"] + report[
        "total_revenue"
    ]
