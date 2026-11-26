"""Pricing: three ways to a price, GST, and rounding that never loses money."""

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.costing import CostLine, calculate
from app.domain.pricing import (
    ROUNDING_STEPS,
    add_gst,
    by_margin,
    by_market,
    by_markup,
    round_up,
    strip_gst,
)

D = Decimal


def _cost(total: str = "500") -> object:
    """A breakdown whose total cost is exactly the number given."""
    return calculate(material=[CostLine("x", 1, D(total))], pieces=1)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("price", "mode", "expected"),
    [
        ("1273.23", "none", "1273.23"),
        ("1273.23", "five", "1275.00"),
        ("1273.23", "ten", "1280.00"),
        ("1270.00", "ten", "1270.00"),  # already a round number stays put
        ("0", "five", "0.00"),
    ],
)
def test_rounding_goes_up_to_the_step(price, mode, expected):
    assert round_up(D(price), mode) == D(expected)


def test_an_unknown_rounding_mode_falls_back_to_the_paise():
    assert round_up(D("10.123"), "nonsense") == D("10.13")


def test_rounding_never_loses_money():
    """The whole reason it rounds up: a rounded-down price gives margin away."""
    for price in ("1.01", "99.99", "100.01", "1273.23"):
        assert round_up(D(price), "five") >= D(price)
        assert round_up(D(price), "ten") >= D(price)


def test_every_mode_is_a_known_step():
    assert set(ROUNDING_STEPS) == {"none", "five", "ten"}


# ---------------------------------------------------------------------------
# GST
# ---------------------------------------------------------------------------


def test_gst_is_added_on_top():
    assert add_gst(D("1000"), D("5")) == D("1050.00")


def test_gst_is_stripped_from_an_inclusive_price():
    assert strip_gst(D("1050"), D("5")) == D("1000.00")


def test_gst_round_trips():
    for rate in ("0", "5", "12", "18"):
        assert strip_gst(add_gst(D("1000"), D(rate)), D(rate)) == D("1000.00")


def test_zero_gst_changes_nothing():
    """An unregistered shop charges nothing extra — and the sheet says so."""
    assert add_gst(D("1170"), D("0")) == D("1170.00")


# ---------------------------------------------------------------------------
# The three methods
# ---------------------------------------------------------------------------


def test_margin_method_produces_the_margin_asked_for():
    s = by_margin(_cost("500"), D("40"), rounding="none")
    assert s.margin_pct == D("40.00")
    assert s.price == D("833.33")


def test_markup_method_produces_the_markup_asked_for():
    s = by_markup(_cost("500"), D("50"), rounding="none")
    assert s.price == D("750.00")


def test_a_markup_is_not_a_margin():
    """The assertion that stops the most expensive confusion in the trade."""
    markup = by_markup(_cost("500"), D("50"), rounding="none")
    margin = by_margin(_cost("500"), D("50"), rounding="none")
    assert markup.price < margin.price
    assert markup.margin_pct == D("33.33")


def test_the_market_method_reports_what_a_price_yields():
    s = by_market(_cost("500"), D("600"))
    assert s.price == D("600.00")
    assert s.margin == D("100.00")
    assert s.margin_pct == D("16.67")


def test_a_market_price_below_cost_is_flagged_unprofitable():
    s = by_market(_cost("500"), D("400"))
    assert s.margin < 0
    assert s.is_profitable is False


def test_every_suggestion_carries_its_price_with_gst():
    s = by_margin(_cost("500"), D("40"), rounding="five", gst_rate=D("5"))
    assert s.price_with_gst == add_gst(s.price, D("5"))


def test_suggestions_are_labelled_for_a_human():
    assert by_margin(_cost(), D("40")).label == "40% margin"
    assert by_markup(_cost(), D("50")).label == "50% markup"
    assert by_market(_cost(), D("600")).label == "At the price you charge"


def test_suggestions_are_immutable():
    from dataclasses import FrozenInstanceError

    s = by_margin(_cost(), D("40"))
    with pytest.raises(FrozenInstanceError):
        s.price = D("1")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

positive = st.decimals(min_value=Decimal("1"), max_value=Decimal("100000"), places=2)
pct = st.decimals(min_value=Decimal("1"), max_value=Decimal("90"), places=1)


@settings(max_examples=100, deadline=None)
@given(cost=positive, target=pct)
def test_a_suggested_price_always_exceeds_cost(cost, target):
    s = by_margin(_cost(str(cost)), target)
    assert s.price > D(str(cost))


@settings(max_examples=100, deadline=None)
@given(cost=positive, target=pct, mode=st.sampled_from(["none", "five", "ten"]))
def test_rounding_never_produces_a_price_below_the_raw_one(cost, target, mode):
    raw = _cost(str(cost)).price_for_margin(target)
    assert round_up(raw, mode) >= raw


@settings(max_examples=80, deadline=None)
@given(cost=positive, rate=st.sampled_from([D("0"), D("5"), D("12"), D("18")]))
def test_gst_round_trip_holds_for_every_rate(cost, rate):
    inclusive = add_gst(D(str(cost)), rate)
    assert abs(strip_gst(inclusive, rate) - D(str(cost))) <= D("0.01")


def test_a_nonsense_gst_rate_is_refused():
    with pytest.raises(ValueError):
        strip_gst(D("100"), D("-150"))
