"""Cost calculation — pure functions, no database, no clock, no framework.

This module is the arithmetic of the business: what one sellable item costs
to make, and what it should be sold for. It exists separately from every
other layer for one reason — **it can be proven correct without a database,
a request or a clock.** Everything here is a function of its arguments.

Two shapes carry the design:

``CostLine``
    One input: a quantity at a unit cost, with a label for the human who
    reads the sheet. Ingredients and packaging are both cost lines; the
    difference is only how they scale.

``CostBreakdown``
    The answer, frozen. A cost breakdown is a *value*, not an object with
    identity — nothing may mutate it after it is computed, which removes a
    whole class of bug from the reporting path.

The scaling rule, which is the point of the whole design:

    material and labour scale with the number of pieces
    overhead scales with the number of pieces (it is per batch ÷ yield)
    packaging does **not** scale with pieces — a nine-piece box is not
    nine wrappers, so it is supplied per size

That asymmetry is why a 9-pc box can earn a lower percentage margin than a
single piece even though it earns more rupees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

#: Money is quantised to paise at every boundary, never carried unrounded.
PENNY = Decimal("0.01")


def _d(value: object) -> Decimal:
    """Coerce to Decimal, refusing anything that is not a number.

    Floats are converted through ``str`` so 0.1 does not arrive as
    0.1000000000000000055511151231257827. Money handled as float is a bug
    waiting for a quarter-end.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("A boolean is not a quantity")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TypeError(f"Not a number: {value!r}") from exc


def _q(value: Decimal) -> Decimal:
    """Round to paise, half-up — the convention a shop expects."""
    return value.quantize(PENNY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CostLine:
    """One costed input: ``quantity`` of something at ``unit_cost`` each.

    ``label`` is for the human reading the sheet ("Dark chocolate 1.2 kg"),
    not for the arithmetic.
    """

    label: str
    quantity: Decimal
    unit_cost: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _d(self.quantity))
        object.__setattr__(self, "unit_cost", _d(self.unit_cost))
        if self.quantity < 0:
            raise ValueError(f"Quantity cannot be negative: {self.label}")
        if self.unit_cost < 0:
            raise ValueError(f"Unit cost cannot be negative: {self.label}")

    @property
    def cost(self) -> Decimal:
        """Unrounded cost of this line. Rounding happens once, at the end."""
        return self.quantity * self.unit_cost


@dataclass(frozen=True)
class CostBreakdown:
    """The cost of one sellable item, and what it implies about price.

    Frozen: computed once, then read. ``total`` is the only figure a caller
    should persist; the components are kept because a cost sheet that cannot
    show its parts is not auditable.
    """

    material: Decimal
    packaging: Decimal
    labour: Decimal
    overhead: Decimal
    wastage: Decimal
    total: Decimal
    #: Per-unit cost before wastage, kept for sensitivity work.
    subtotal: Decimal = field(default=Decimal("0.00"))

    @property
    def components(self) -> dict[str, Decimal]:
        """Every line of the sheet, in the order it is shown."""
        return {
            "material": self.material,
            "packaging": self.packaging,
            "labour": self.labour,
            "overhead": self.overhead,
            "wastage": self.wastage,
        }

    def margin_at(self, price: Decimal) -> Decimal:
        """Gross margin in rupees at a given selling price."""
        return _q(_d(price) - self.total)

    def margin_pct_at(self, price: Decimal) -> Decimal:
        """Gross margin as a percentage **of the price**.

        Not of the cost. A 50% markup is a 33% margin, and mixing the two is
        the most common pricing error in small food businesses.
        """
        price = _d(price)
        if price <= 0:
            return Decimal("0.00")
        return (self.margin_at(price) / price * 100).quantize(Decimal("0.01"))

    def markup_pct_at(self, price: Decimal) -> Decimal:
        """How many times the cost the price represents, minus one."""
        if self.total <= 0:
            return Decimal("0.00")
        return ((_d(price) - self.total) / self.total * 100).quantize(Decimal("0.01"))

    def price_for_margin(self, margin_pct: Decimal) -> Decimal:
        """The price that yields ``margin_pct`` of the price as margin.

        ``price = cost / (1 - margin)``. A margin of 100% has no finite
        price, so it is refused rather than returning infinity.
        """
        pct = _d(margin_pct)
        if pct >= 100:
            raise ValueError("A margin of 100% or more has no finite price")
        if pct <= -100:
            raise ValueError("A margin below -100% has no meaning")
        return _q(self.total / (Decimal(1) - pct / 100))

    def price_for_markup(self, markup_pct: Decimal) -> Decimal:
        """The price that is ``markup_pct`` above cost."""
        return _q(self.total * (Decimal(1) + _d(markup_pct) / 100))

    def break_even(self) -> Decimal:
        """The price at which nothing is lost and nothing is made."""
        return self.total


def calculate(
    *,
    material: list[CostLine],
    packaging: list[CostLine] | None = None,
    pieces: int = 1,
    yield_pieces: int = 1,
    labour_minutes: Decimal | int = 0,
    labour_rate_per_hour: Decimal | int = 0,
    overhead_per_batch: Decimal | int = 0,
    wastage_pct: Decimal | int = 0,
) -> CostBreakdown:
    """Cost of **one sellable item** made from a batch recipe.

    ``material`` is the recipe for a whole batch; ``yield_pieces`` says how
    many pieces that batch makes. ``pieces`` is how many go in the item
    being costed — a 9-pc box passes ``pieces=9``.

    ``packaging`` is per item, not per piece, because a box does not scale
    with its contents.

    ``labour_minutes`` is the time for the **whole batch**; it is divided by
    the yield and multiplied back up by the pieces, so a bigger box carries
    proportionally more labour.

    ``wastage_pct`` applies to material plus labour — spoilage and trim are
    costs of making, not of boxing.
    """
    pieces = int(pieces)
    yield_pieces = int(yield_pieces)
    if pieces <= 0:
        raise ValueError("An item must contain at least one piece")
    if yield_pieces <= 0:
        raise ValueError("A batch must yield at least one piece")

    rate = _d(labour_rate_per_hour)
    minutes = _d(labour_minutes)
    overhead_batch = _d(overhead_per_batch)
    wastage = _d(wastage_pct)

    if rate < 0 or minutes < 0 or overhead_batch < 0:
        raise ValueError("Labour and overhead cannot be negative")
    if not (Decimal(0) <= wastage < 100):
        raise ValueError("Wastage must be between 0 and 100 percent")

    material_batch = sum((line.cost for line in (material or [])), Decimal("0"))
    material_cost = material_batch * Decimal(pieces) / Decimal(yield_pieces)

    packaging_cost = sum((line.cost for line in (packaging or [])), Decimal("0"))

    labour_batch = rate * minutes / Decimal(60)
    labour_cost = labour_batch * Decimal(pieces) / Decimal(yield_pieces)

    overhead_cost = overhead_batch * Decimal(pieces) / Decimal(yield_pieces)

    subtotal = material_cost + labour_cost
    wastage_cost = subtotal * wastage / Decimal(100)

    total = material_cost + packaging_cost + labour_cost + overhead_cost + wastage_cost

    return CostBreakdown(
        material=_q(material_cost),
        packaging=_q(packaging_cost),
        labour=_q(labour_cost),
        overhead=_q(overhead_cost),
        wastage=_q(wastage_cost),
        total=_q(total),
        subtotal=_q(subtotal),
    )


__all__ = ["CostLine", "CostBreakdown", "calculate"]
