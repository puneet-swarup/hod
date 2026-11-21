# ADR-0017: `order_date` is a local calendar date

## Status

Accepted

## Date

2026-11-21

## Context

ADR-0015 fixed the display side of time: stored instants are UTC and are
converted at the boundary, while user-entered datetimes keep local
intent. `order_date` was the one column that fell between the two:

- The order form sends a date (`2026-11-21`), which `datetime.fromisoformat`
  turns into local midnight — a *local* value.
- `_build_order` defaulted it to `utcnow()` when absent — a *UTC* value.
- `reports_service` and `export_service` compared it against UTC month and
  day bounds, with a docstring claiming it was stored as UTC.

Nothing broke visibly, because a +5h30m shift across a local midnight
still lands inside the same reporting window. It was one late-evening
order away from a wrong month in a tax export.

## Decision

`order_date` is **the business calendar date the order was placed**,
stored as a naive LOCAL datetime.

1. Writers: a supplied value is used as given (the form sends local
   midnight); when absent, the default is `business_now()`, never
   `utcnow()`.
2. Readers that filter by it (`reports_service`, `export_service`) build
   **local naive** bounds — no timezone conversion on either side.
3. Display uses the `ld` / `ldt` filters, which format without
   conversion. Running `order_date` through `dt` would show a 05:30 that
   never happened.
4. Columns that are true instants (`created_at`, `updated_at`,
   `changed_at`, `received_at`) keep the ADR-0015 rule: naive UTC in,
   `dt` on the way out.

`export_service` therefore returns two ranges: UTC bounds for
`Payment.received_at`, local bounds for `Order.order_date`. Mixing them
shifts a day boundary by 5h30m — which is exactly the bug this ADR
prevents from coming back.

## Consequences

- (+) A month's revenue, a tax export and the orders list all agree on
  which day an order belongs to.
- (+) `created_at` still records the exact instant, so audit and
  "when was this really placed" remain answerable.
- (−) Two datetime semantics coexist in the schema. They are now explicit:
  ADR-0015 for instants, this ADR for calendar dates, and both are
  covered by tests.
- (−) Historical rows written by the API default (UTC-naive) may sit
  up to 5h30m off a local midnight. The date part is unaffected for any
  order placed between 05:30 and 23:59 local; no data is rewritten.
