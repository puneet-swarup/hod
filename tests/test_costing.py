"""The cost calculator: arithmetic that can be proven without a database.

Two kinds of test here.

**Examples** pin the behaviour a person would check by hand: a batch of 24
brownies, a 9-piece box, a known total. They are the specification.

**Properties** state rules that must hold for *every* input — that a price
built for a 40% margin really yields 40%, that cost never falls when an
ingredient gets dearer, that no component is ever negative. Hypothesis
generates the inputs, so these catch the cases nobody thought to write.
"""

from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.domain.costing import CostBreakdown, CostLine, calculate

D = Decimal


def _brownie_batch(pieces: int = 9, **overrides) -> CostBreakdown:
    """A real recipe: one tray of 24 brownies, costed for a 9-piece box."""
    params = {
        "material": [
            CostLine("dark chocolate", D("1.2"), D("450")),
            CostLine("butter", D("0.8"), D("550")),
            CostLine("sugar", D("0.6"), D("45")),
            CostLine("eggs", D("12"), D("7")),
            CostLine("maida", D("0.3"), D("40")),
            CostLine("nutella", D("0.8"), D("380")),
            CostLine("walnuts", D("0.2"), D("900")),
        ],
        "packaging": [CostLine("box + insert", D("1"), D("35"))],
        "pieces": pieces,
        "yield_pieces": 24,
        "labour_minutes": D("90"),
        "labour_rate_per_hour": D("100"),
        "overhead_per_batch": D("120"),
        "wastage_pct": D("5"),
    }
    params.update(overrides)
    return calculate(**params)


# ---------------------------------------------------------------------------
# Examples — the numbers a person would check by hand
# ---------------------------------------------------------------------------


def test_a_cost_line_multiplies_quantity_by_unit_cost():
    assert CostLine("butter", D("0.8"), D("550")).cost == D("440.0")


def test_material_is_the_batch_scaled_to_the_pieces_in_the_item():
    b = _brownie_batch(pieces=9)
    # Batch material ₹1,587.50 over 24 pieces, times 9.
    assert b.material == D("595.13")


def test_packaging_does_not_scale_with_pieces():
    """A nine-piece box is one box, not nine."""
    small = _brownie_batch(pieces=1)
    large = _brownie_batch(pieces=9)
    assert small.packaging == large.packaging == D("35.00")


def test_labour_scales_with_pieces():
    small = _brownie_batch(pieces=1)
    large = _brownie_batch(pieces=9)
    assert large.labour == small.labour * 9


def test_wastage_applies_to_material_and_labour_only():
    b = _brownie_batch(pieces=9)
    expected = (b.material + b.labour) * D("0.05")
    assert abs(b.wastage - expected) <= D("0.01")


def test_the_total_is_the_sum_of_its_parts():
    b = _brownie_batch()
    parts = b.material + b.packaging + b.labour + b.overhead + b.wastage
    assert abs(b.total - parts) <= D("0.02")  # each part rounded to the paise


def test_a_known_total():
    """The full worked example, pinned."""
    assert _brownie_batch().total == D("763.94")


def test_margin_is_a_share_of_the_price_not_the_cost():
    b = _brownie_batch()
    price = D("1170")
    assert b.margin_at(price) == D("406.06")
    assert b.margin_pct_at(price) == D("34.71")
    # Markup is the other number people confuse with margin.
    assert b.markup_pct_at(price) == D("53.15")


def test_price_for_margin_inverts_margin_at():
    b = _brownie_batch()
    price = b.price_for_margin(D("40"))
    assert b.margin_pct_at(price) == D("40.00")


def test_price_for_markup_inverts_markup_at():
    b = _brownie_batch()
    price = b.price_for_markup(D("50"))
    assert b.markup_pct_at(price) == D("50.00")


def test_a_markup_is_not_a_margin():
    """The single most expensive confusion in small-business pricing."""
    b = _brownie_batch()
    markup_price = b.price_for_markup(D("50"))
    assert b.margin_pct_at(markup_price) < D("50")
    assert b.margin_pct_at(markup_price) == D("33.33")


def test_break_even_is_the_total():
    b = _brownie_batch()
    assert b.break_even() == b.total
    assert b.margin_at(b.break_even()) == D("0.00")


def test_the_breakdown_is_immutable():
    """A cost breakdown is a value: computed once, then read."""
    from dataclasses import FrozenInstanceError

    b = _brownie_batch()
    with pytest.raises(FrozenInstanceError):
        b.total = D("1")  # type: ignore[misc]


def test_components_are_reported_in_sheet_order():
    assert list(_brownie_batch().components) == [
        "material",
        "packaging",
        "labour",
        "overhead",
        "wastage",
    ]


# ---------------------------------------------------------------------------
# Refusals — the calculator says no rather than returning nonsense
# ---------------------------------------------------------------------------


def test_a_negative_quantity_is_refused():
    with pytest.raises(ValueError):
        CostLine("butter", D("-1"), D("550"))


def test_a_negative_unit_cost_is_refused():
    with pytest.raises(ValueError):
        CostLine("butter", D("1"), D("-550"))


def test_a_non_number_is_refused():
    with pytest.raises(TypeError):
        CostLine("butter", "lots", D("550"))


def test_a_boolean_is_not_a_quantity():
    with pytest.raises(TypeError):
        CostLine("butter", True, D("550"))


def test_zero_pieces_is_refused():
    with pytest.raises(ValueError):
        calculate(material=[], pieces=0)


def test_zero_yield_is_refused():
    with pytest.raises(ValueError):
        calculate(material=[], yield_pieces=0)


def test_a_margin_of_one_hundred_percent_has_no_price():
    with pytest.raises(ValueError):
        _brownie_batch().price_for_margin(D("100"))


def test_wastage_of_one_hundred_percent_is_refused():
    with pytest.raises(ValueError):
        calculate(material=[], wastage_pct=100)


def test_negative_labour_is_refused():
    with pytest.raises(ValueError):
        calculate(material=[], labour_rate_per_hour=-1)


def test_no_recipe_still_costs_the_packaging():
    """A product with no recipe is not free — it still has a box."""
    b = calculate(material=[], packaging=[CostLine("box", 1, "20")], pieces=1)
    assert b.total == D("20.00")
    assert b.material == D("0.00")


# ---------------------------------------------------------------------------
# Properties — true for every input, not just the ones written by hand
# ---------------------------------------------------------------------------

money = st.decimals(min_value=Decimal("0"), max_value=Decimal("100000"), places=2)
positive_int = st.integers(min_value=1, max_value=200)
pct = st.decimals(min_value=Decimal("0"), max_value=Decimal("99"), places=2)


@settings(max_examples=120, deadline=None)
@given(
    quantity=money,
    unit_cost=money,
    pieces=positive_int,
    yield_pieces=positive_int,
    rate=money,
    minutes=st.decimals(min_value=Decimal("0"), max_value=Decimal("600"), places=1),
    overhead=money,
    wastage=pct,
)
def test_no_component_is_ever_negative(quantity, unit_cost, pieces, yield_pieces,
                                       rate, minutes, overhead, wastage):
    b = calculate(
        material=[CostLine("x", quantity, unit_cost)],
        pieces=pieces,
        yield_pieces=yield_pieces,
        labour_rate_per_hour=rate,
        labour_minutes=minutes,
        overhead_per_batch=overhead,
        wastage_pct=wastage,
    )
    assert all(v >= 0 for v in b.components.values())
    assert b.total >= 0


@settings(max_examples=100, deadline=None)
@given(material_cost=money, pieces=positive_int, yield_pieces=positive_int)
def test_the_total_never_falls_when_an_ingredient_gets_dearer(material_cost, pieces, yield_pieces):
    cheap = calculate(
        material=[CostLine("x", 1, material_cost)],
        pieces=pieces,
        yield_pieces=yield_pieces,
    )
    dearer = calculate(
        material=[CostLine("x", 1, material_cost + Decimal("10"))],
        pieces=pieces,
        yield_pieces=yield_pieces,
    )
    assert dearer.total >= cheap.total


@settings(max_examples=100, deadline=None)
@given(material_cost=money, pieces=positive_int, yield_pieces=positive_int, target=pct)
def test_a_price_built_for_a_margin_yields_that_margin(material_cost, pieces, yield_pieces, target):
    """The round trip: price_for_margin → margin_at → the margin asked for.

    Asserted in rupees rather than percentage points, because that is the
    statement that is true for every input. On a ₹1 item one paise of
    rounding is half a percentage point; on a ₹1,000 item it is nothing.
    """
    b = calculate(
        material=[CostLine("x", 1, material_cost)],
        pieces=pieces,
        yield_pieces=yield_pieces,
    )
    assume(b.total > Decimal("0"))
    price = b.price_for_margin(target)
    expected = price * target / Decimal(100)
    assert abs(b.margin_at(price) - expected) <= Decimal("0.02")


@settings(max_examples=80, deadline=None)
@given(pieces=positive_int, other=positive_int)
def test_material_scales_linearly_with_pieces(pieces, other):
    one = _brownie_batch(pieces=pieces)
    two = _brownie_batch(pieces=pieces * 2)
    assert abs(two.material - one.material * 2) <= Decimal("0.05")


# ---------------------------------------------------------------------------
# The edges coverage found
# ---------------------------------------------------------------------------


def test_a_zero_price_has_no_margin():
    """Not an error — a price of nothing is simply all loss."""
    assert _brownie_batch().margin_pct_at(Decimal("0")) == Decimal("0.00")


def test_markup_on_a_free_item_is_zero_rather_than_infinite():
    free = calculate(material=[], pieces=1)
    assert free.markup_pct_at(Decimal("100")) == Decimal("0.00")


def test_a_margin_below_minus_one_hundred_is_refused():
    with pytest.raises(ValueError):
        _brownie_batch().price_for_margin(Decimal("-150"))
