"""Pricing: turning a cost into a price, and a price into what it pays.

Pure functions, like ``costing``. Three ways to arrive at a price, because a
baker uses all three at different times:

``by_margin``   "I want 40% of the price to be profit" — the P&L way
``by_markup``   "I double my cost" — the habit way
``by_market``   "the market pays ₹1,200" — then show what that yields

The first two are **not the same number**: a 50% markup is a 33.3% margin.
That confusion is the most expensive one in small food businesses, so the
two are separate named functions rather than a flag.

Rounding is a business decision, not a formatting one — a price ending in 7
looks like an accident, and a price rounded down can lose money. Rounding is
therefore always **up**, and the modes are explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from app.domain.costing import CostBreakdown

PENNY = Decimal("0.01")

#: How a suggested price is rounded. Keys match ``costing_settings.price_rounding``.
ROUNDING_STEPS: dict[str, Decimal] = {
    "none": PENNY,
    "five": Decimal("5"),
    "ten": Decimal("10"),
}


def _d(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def round_up(price: Decimal, mode: str = "five") -> Decimal:
    """Round a price **up** to the nearest step.

    Up, never down: rounding a price down to make it look tidy quietly gives
    away margin on every sale. A suggested ₹1,273.23 becomes ₹1,275 at the
    five-rupee step.
    """
    step = ROUNDING_STEPS.get(mode, PENNY)
    price = _d(price)
    if price <= 0:
        return Decimal("0.00")
    steps = (price / step).to_integral_value(rounding=ROUND_CEILING)
    return (steps * step).quantize(PENNY)


def add_gst(price: Decimal, gst_rate: Decimal) -> Decimal:
    """A pre-tax price plus GST — what the customer actually hands over."""
    return (_d(price) * (1 + _d(gst_rate) / 100)).quantize(PENNY, rounding=ROUND_HALF_UP)


def strip_gst(price_with_gst: Decimal, gst_rate: Decimal) -> Decimal:
    """The pre-tax value inside a GST-inclusive price."""
    rate = _d(gst_rate)
    if rate <= -100:
        raise ValueError("A GST rate below -100% has no meaning")
    return (_d(price_with_gst) / (1 + rate / 100)).quantize(PENNY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PriceSuggestion:
    """One way of arriving at a price, and what it yields at that price."""

    method: str  # "margin" | "markup" | "market"
    label: str
    price: Decimal
    margin: Decimal
    margin_pct: Decimal
    #: The price with GST added, when the shop charges it.
    price_with_gst: Decimal

    @property
    def is_profitable(self) -> bool:
        return self.margin > 0


def by_margin(
    breakdown: CostBreakdown,
    margin_pct: Decimal,
    *,
    rounding: str = "five",
    gst_rate: Decimal = Decimal("0"),
) -> PriceSuggestion:
    """The price that makes ``margin_pct`` of the price profit."""
    raw = breakdown.price_for_margin(_d(margin_pct))
    price = round_up(raw, rounding)
    return _suggestion("margin", f"{margin_pct}% margin", price, breakdown, gst_rate)


def by_markup(
    breakdown: CostBreakdown,
    markup_pct: Decimal,
    *,
    rounding: str = "five",
    gst_rate: Decimal = Decimal("0"),
) -> PriceSuggestion:
    """The price that is ``markup_pct`` above cost."""
    raw = breakdown.price_for_markup(_d(markup_pct))
    price = round_up(raw, rounding)
    return _suggestion("markup", f"{markup_pct}% markup", price, breakdown, gst_rate)


def by_market(
    breakdown: CostBreakdown,
    market_price: Decimal,
    *,
    gst_rate: Decimal = Decimal("0"),
) -> PriceSuggestion:
    """Take the price the market pays, and report what it yields.

    No rounding: this is the price being charged, not a suggestion.
    """
    price = _d(market_price).quantize(PENNY)
    return _suggestion("market", "At the price you charge", price, breakdown, gst_rate)


def _suggestion(
    method: str,
    label: str,
    price: Decimal,
    breakdown: CostBreakdown,
    gst_rate: Decimal,
) -> PriceSuggestion:
    return PriceSuggestion(
        method=method,
        label=label,
        price=price,
        margin=breakdown.margin_at(price),
        margin_pct=breakdown.margin_pct_at(price),
        price_with_gst=add_gst(price, gst_rate),
    )


__all__ = [
    "PriceSuggestion",
    "ROUNDING_STEPS",
    "add_gst",
    "strip_gst",
    "round_up",
    "by_margin",
    "by_markup",
    "by_market",
]
