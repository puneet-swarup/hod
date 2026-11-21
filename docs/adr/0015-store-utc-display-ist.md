# ADR-0015: Store UTC, display in the business timezone

## Status

Accepted — supersedes [ADR-0014](0014-local-time-over-utc.md)

## Date

2026-11-21

## Context

ADR-0014 chose to store local time (`datetime.now()`) so that stored
timestamps matched the user's wall clock. The code has since moved to
the opposite policy: `app/utils/time.py` stores **naive UTC**
(`utcnow()`) and converts to `settings.business_timezone` only at the
display boundary, via the `dt` / `d` Jinja filters registered in
`app/main.py`.

The move was right — the server's own clock is not a contract, and a
hosted box runs in UTC whether or not anyone remembers to set it. But
ADR-0014 was never marked superseded, and two templates were still
calling `strftime()` on the raw stored value:

- `audit.html` — the audit log's "Time" column
- `reports.html` — the "Generated" column

Both showed UTC, i.e. 5h30m behind what the user's clock said. That is
the "timestamp should be in IST" report.

## Decision

1. **Storage**: every audit/tracking timestamp is naive UTC, written by
   `utcnow()`. No exceptions, no `datetime.now()`.
2. **Display**: templates never call `strftime()` on a stored timestamp.
   They use the `dt` / `d` filters, which convert UTC → business timezone.
3. **User-entered datetimes are not UTC.** `fulfillment_date` and
   `order_date` carry the *customer's local intent* ("ready at 15:00").
   They are stored as typed and compared against the local date
   (`today_service._today_local()`), and they are displayed raw. Running
   them through `dt` would shift them by +5h30m and is a bug.
4. Any value derived from a filesystem timestamp (e.g. report mtimes) is
   converted to naive UTC at the service layer, so rule 2 stays true.

## Consequences

- (+) Every screen agrees with the wall clock, on any host, in any
  server timezone.
- (+) The rule is mechanical and testable: `tests/test_ist_display.py`
  pins both the display conversion and the UTC normalisation of report
  mtimes.
- (−) Two datetime semantics coexist in the schema (UTC instants vs local
  wall-clock intents). The distinction is documented in
  `app/utils/time.py` and in this ADR; new fields must pick one
  deliberately.
- (−) A future multi-timezone bakery would need the local-intent fields
  to carry an explicit zone. Not a problem for one bakery in India.
