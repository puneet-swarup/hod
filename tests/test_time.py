"""Timezone helper tests.

These lock in the storage/display policy: naive UTC in the DB, converted
to the business timezone only at the boundaries. They are deliberately
run with a non-IST server TZ so a regression that falls back to server
local time is caught.
"""

import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import get_settings
from app.utils.time import (
    business_day_bounds_utc,
    business_now,
    business_today_bounds_utc,
    to_business_tz,
    utcnow,
)

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def non_ist_server_tz(monkeypatch):
    """Force the process TZ away from IST so server-local bugs surface."""
    monkeypatch.setenv("TZ", "UTC")
    if hasattr(os, "tzset"):
        os.tzset()
    yield
    if hasattr(os, "tzset"):
        os.tzset()


def test_utcnow_is_naive_utc():
    now = utcnow()
    assert now.tzinfo is None
    # Within a few seconds of true UTC.
    delta = abs((datetime.now(UTC).replace(tzinfo=None) - now).total_seconds())
    assert delta < 5


def test_business_now_uses_business_tz(non_ist_server_tz):
    now = business_now()
    # IST is +05:30 year-round (no DST).
    assert now.utcoffset().total_seconds() == 5.5 * 3600


def test_business_now_differs_from_server_utc(non_ist_server_tz):
    """With TZ=UTC, business_now must still be IST (+05:30)."""
    now = business_now()
    assert now.utcoffset().total_seconds() == 5.5 * 3600


def test_to_business_tz_converts_naive_utc():
    # 2026-01-01 06:30 UTC == 2026-01-01 12:00 IST
    naive_utc = datetime(2026, 1, 1, 6, 30, 0)
    local = to_business_tz(naive_utc)
    assert local.hour == 12
    assert local.minute == 0
    assert local.tzinfo is not None


def test_to_business_tz_none():
    assert to_business_tz(None) is None


def test_business_today_bounds_span_one_day():
    start, end = business_today_bounds_utc()
    assert start.tzinfo is None and end.tzinfo is None
    # Both are naive UTC; end must be after start, less than 24h apart.
    assert end > start
    assert (end - start).total_seconds() < 24 * 3600


def test_business_day_bounds_utc_ist_offsets():
    start, end = business_day_bounds_utc("2026-03-15")
    # 2026-03-15 00:00 IST == 2026-03-14 18:30 UTC
    assert start == datetime(2026, 3, 14, 18, 30, 0)
    # End is 2026-03-15 23:59:59.999999 IST == 18:29:59.999999 UTC
    assert end.date() == datetime(2026, 3, 15).date()
    assert end.hour == 18


def test_settings_business_timezone_default_is_ist():
    # The default must remain Asia/Kolkata unless explicitly overridden.
    assert get_settings().business_timezone == "Asia/Kolkata"
