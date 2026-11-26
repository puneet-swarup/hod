# 0019 — Three named pricing methods, and rounding that only goes up

**Status:** Accepted
**Date:** 2026-11-26
**Related:** [0018](0018-recipes-keyed-to-family.md), [`docs/ENGINEERING_STANDARDS.md`](../ENGINEERING_STANDARDS.md)

---

## Context

A price can be reached from a cost in more than one way, and the ways are
not equivalent. The two that matter:

- **Margin** — profit as a share of the *price*: `price = cost ÷ (1 − m)`
- **Markup** — profit as a share of the *cost*: `price = cost × (1 + m)`

At 50%, these give ₹1,000 and ₹750 on a ₹500 cost. A business that thinks it
is earning 50% on a 50% markup is earning 33.3%, and will discover the
difference at the end of a bad year.

There is also a third, which is how most small bakeries actually price: the
market pays what it pays, and the cost is either covered or it is not.

Separately, a suggested price is rarely a round number (₹1,273.23), and a
shop wants something it can say out loud.

## Options

**A. One function with a mode flag** — `price(cost, mode="margin")`.
Compact, but invites passing the wrong mode and reading the result as the
other. The failure is silent and expensive.

**B. Three named functions** — `by_margin`, `by_markup`, `by_market`, each
returning the same `PriceSuggestion` carrying the price, the margin in
rupees and as a percentage, and the GST-inclusive price.

**C. A strategy class per method.** Two implementations do not justify it;
the three methods are pure functions of a cost and a number.

## Decision

**Option B.** Three named functions, each returning a frozen
`PriceSuggestion`. The names appear in the UI, so the sheet says
"40% margin" and "50% markup" rather than two numbers a person must
interpret.

Rounding is a separate, explicit step:

- always **up**, never to nearest — rounding a price down to make it tidy
  gives away margin on every sale, and no one would choose that if asked
- three modes: exact, to ₹5, to ₹10, matching `costing_settings`
- the market method is **not** rounded: that price is being charged, not
  suggested

GST is a presentation concern, so `add_gst` and `strip_gst` are separate
functions and every suggestion carries `price_with_gst`. A business that is
not registered sees the rate as zero and the line says so, rather than
hiding a figure that will matter the day it registers.

## Consequences

**Good**

- The markup/margin confusion cannot happen silently: they are different
  functions with different names, and a test asserts they differ.
- Rounding cannot lose money, because it can only go up. A property test
  asserts it across 100 generated prices.
- The three methods sit side by side on one screen, which is how the
  decision is actually made.

**Bad**

- Three functions to keep in step. Mitigated: they share one `_suggestion`
  helper, so the shape of the answer cannot drift.
- Rounding up means the effective margin is slightly better than the target,
  which can make a "40% margin" look like 40.1%. Accepted: erring upward is
  the right direction for the business.

**Neutral**

- `apply_price` is the only function that writes a price, and it audits the
  old and new value. Nothing calls it automatically — the suggestion becomes
  a price only when a person presses the button.

## What would make us revisit this

- A price list that varies by channel at the *suggestion* stage (retail vs
  B2B) rather than at the order stage — that would need a fourth method.
- A rounding convention that is not a round number (₹99 endings), which
  would add a mode rather than change the direction.
