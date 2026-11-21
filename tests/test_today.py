"""Tests for the Today page — dispatch list and production aggregation."""

from datetime import datetime, timedelta
from decimal import Decimal

from app.models import OrderStatus
from app.services.order_service import create_order, update_status
from app.services.today_service import dispatch_today, production_this_week
from app.utils.time import business_today_bounds_utc


def _iso_local(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def _mk_order(db, customer, product, qty, fulfillment_dt, advance=0):
    return create_order(
        db,
        {
            "customer_id": customer.id,
            "items": [{"product_id": product.id, "quantity": qty}],
            "fulfillment_date": _iso_local(fulfillment_dt),
            "advance_paid": advance,
        },
    )


def test_dispatch_includes_today_orders(db, customer, product):
    today_start, _ = business_today_bounds_utc()
    today_noon = today_start + timedelta(hours=6)  # roughly noon local

    _mk_order(db, customer, product, 1, today_noon)

    results = dispatch_today(db)
    assert len(results) == 1
    assert results[0].customer.id == customer.id


def test_dispatch_excludes_future_and_cancelled(db, customer, product):
    today_start, _ = business_today_bounds_utc()
    today_noon = today_start + timedelta(hours=6)
    tomorrow_noon = today_noon + timedelta(days=1)

    o_today = _mk_order(db, customer, product, 1, today_noon)
    _mk_order(db, customer, product, 1, tomorrow_noon)

    # Cancel the today order
    update_status(db, o_today.id, "CANCELLED")

    results = dispatch_today(db)
    assert len(results) == 0


def test_production_buckets_by_date(db, customer, product):
    today_start, _ = business_today_bounds_utc()
    today_noon = today_start + timedelta(hours=6)
    tomorrow_noon = today_noon + timedelta(days=1)
    three_days = today_noon + timedelta(days=3)

    _mk_order(db, customer, product, 2, today_noon)
    _mk_order(db, customer, product, 3, tomorrow_noon)
    _mk_order(db, customer, product, 5, three_days)

    prod = production_this_week(db)

    assert len(prod["urgent"]) == 1
    assert prod["urgent"][0]["qty"] == 2

    assert len(prod["tomorrow"]) == 1
    assert prod["tomorrow"][0]["qty"] == 3

    assert len(prod["later"]) == 1
    assert prod["later"][0]["qty"] == 5

    assert prod["total_units"] == 10


def test_production_aggregates_same_sku(db, customer, product):
    today_start, _ = business_today_bounds_utc()
    today_noon = today_start + timedelta(hours=6)

    _mk_order(db, customer, product, 2, today_noon)
    _mk_order(db, customer, product, 3, today_noon)

    prod = production_this_week(db)
    assert len(prod["urgent"]) == 1
    assert prod["urgent"][0]["qty"] == 5
    assert prod["urgent"][0]["order_count"] == 2


def test_production_excludes_ready_orders(db, customer, product):
    today_start, _ = business_today_bounds_utc()
    today_noon = today_start + timedelta(hours=6)

    o = _mk_order(db, customer, product, 1, today_noon)
    # Move through the state machine to READY
    update_status(db, o.id, "IN_PROGRESS")
    update_status(db, o.id, "READY")

    prod = production_this_week(db)
    assert prod["total_units"] == 0


def test_production_respects_7_day_horizon(db, customer, product):
    today_start, _ = business_today_bounds_utc()
    far_future = today_start + timedelta(days=30)

    _mk_order(db, customer, product, 1, far_future)

    prod = production_this_week(db)
    assert prod["total_units"] == 0


# ---------------------------------------------------------------------------
# Overdue orders (regression: past-due work vanished from the production list)
# ---------------------------------------------------------------------------


def test_production_shows_overdue_orders(db, customer, product):
    """An order whose date has passed and was never delivered must stay
    visible in production, in its own bucket."""
    today_start, _ = business_today_bounds_utc()
    yesterday_noon = today_start + timedelta(hours=6) - timedelta(days=1)

    _mk_order(db, customer, product, 4, yesterday_noon)

    prod = production_this_week(db)
    assert len(prod["overdue"]) == 1
    assert prod["overdue"][0]["qty"] == 4
    assert prod["urgent"] == []
    assert prod["later"] == []
    assert prod["total_units"] == 4


def test_overdue_bucket_excludes_delivered_orders(db, customer, product):
    today_start, _ = business_today_bounds_utc()
    yesterday_noon = today_start + timedelta(hours=6) - timedelta(days=1)

    o = _mk_order(db, customer, product, 1, yesterday_noon)
    update_status(db, o.id, "IN_PROGRESS")
    update_status(db, o.id, "READY")
    update_status(db, o.id, "DELIVERED")

    prod = production_this_week(db)
    assert prod["overdue"] == []
    assert prod["total_units"] == 0


def test_overdue_bucket_excludes_cancelled_orders(db, customer, product):
    today_start, _ = business_today_bounds_utc()
    yesterday_noon = today_start + timedelta(hours=6) - timedelta(days=1)

    o = _mk_order(db, customer, product, 1, yesterday_noon)
    update_status(db, o.id, "CANCELLED")

    prod = production_this_week(db)
    assert prod["overdue"] == []
    assert prod["total_units"] == 0


def test_overdue_keeps_in_progress_orders(db, customer, product):
    """Started but not finished is exactly the case that must not disappear."""
    today_start, _ = business_today_bounds_utc()
    yesterday_noon = today_start + timedelta(hours=6) - timedelta(days=1)

    o = _mk_order(db, customer, product, 2, yesterday_noon)
    update_status(db, o.id, "IN_PROGRESS")

    prod = production_this_week(db)
    assert len(prod["overdue"]) == 1
    assert prod["overdue"][0]["qty"] == 2


def test_overdue_carries_the_past_fulfillment_timestamp(db, customer, product):
    """The row must expose when it was actually due, for display."""
    today_start, _ = business_today_bounds_utc()
    due = today_start + timedelta(hours=6) - timedelta(days=2)

    _mk_order(db, customer, product, 1, due)

    prod = production_this_week(db)
    assert prod["overdue"][0]["earliest"] == due


def test_production_row_earliest_is_the_fulfillment_datetime(db, customer, product):
    """Requirement: the production list shows the timestamp, not just a count."""
    today_start, _ = business_today_bounds_utc()
    noon = today_start + timedelta(hours=6)
    evening = noon + timedelta(hours=5)

    _mk_order(db, customer, product, 1, evening)
    _mk_order(db, customer, product, 1, noon)

    row = production_this_week(db)["urgent"][0]
    assert row["earliest"] == noon
    assert row["order_count"] == 2


def test_overdue_row_shows_the_oldest_due_date(db, customer, product):
    """Same SKU, two late orders: the row reports the most overdue date."""
    today_start, _ = business_today_bounds_utc()
    base = today_start + timedelta(hours=6)
    older = base - timedelta(days=5)
    _mk_order(db, customer, product, 1, base - timedelta(days=1))
    _mk_order(db, customer, product, 1, older)

    prod = production_this_week(db)
    assert len(prod["overdue"]) == 1
    assert prod["overdue"][0]["earliest"] == older
    assert prod["overdue"][0]["order_count"] == 2
