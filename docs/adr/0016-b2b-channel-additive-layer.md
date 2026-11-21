# ADR-0016: B2B channel as an additive layer over retail orders

## Status

Accepted

## Date

2026-11-21

## Context

The bakery wants to optionally supply shops and franchisees. Each partner
negotiates its own price per product, its own credit terms, minimum order
value and dispatch days. Two commercial models are in use in the trade:

- **Unit price** — the partner pays an agreed rate per product, often in
  quantity slabs.
- **Commission** — the partner sells at MRP and keeps a percentage; the
  bakery invoices MRP minus that commission.

Both must be supported, because partners ask for different things and a
partner can switch model between contracts. The existing app models one
channel: a retail customer, an advance, a ready-by time. It must keep
working untouched — retail is the business.

Constraints carried into the design: data is sacred (additive migrations
only), one order pipeline (stock, COGS, invoices, reports must not
diverge), and no new navigation clutter for a bakery that never signs a
partner.

## Decision

**1. A partner is a layer, not a second order system.**

`orders` gains exactly two columns, both nullable/defaulted:

```sql
channel    VARCHAR(10) NOT NULL DEFAULT 'RETAIL'
account_id INTEGER NULL
```

Every B2B order is a normal `Order` with normal `OrderItem` rows, so
production, ingredient deduction, COGS, invoicing and reports are shared
by construction. The alternative — a separate B2B order table — would
have duplicated the most safety-critical code in the app.

**2. Price lives in the contract, never on the product.**

`products.base_price` is the retail price and is never overwritten.
Wholesale rates live in `b2b_price_items`, attached to a versioned
`b2b_contracts` row. `OrderItem.unit_price` is already a snapshot, so an
old order can never be repriced by a later contract edit.

**3. Both pricing models live on the contract, not in two code paths.**

`b2b_contracts.pricing_mode` is `UNIT_PRICE` or `COMMISSION`, with an
optional `default_commission_pct`. A `b2b_price_item` may carry
`unit_price` **or** `commission_pct` for one product and slab, overriding
the contract default. Resolution order:

```
covering contract
  -> best slab for (product, qty)      -> its unit_price
                                       -> else its commission_pct
  -> else contract default commission  -> MRP x (1 - pct)
  -> else retail price
```

`resolve_price()` returns a `source` (`CONTRACT` / `COMMISSION` /
`RETAIL`) so the UI can badge what the partner is being charged and warn
when a SKU has no agreed rate. Commission is taken off the taxable base
price (before GST), not off the GST-inclusive amount.

**4. Commercial checks warn; they never block.**

Minimum order value, cut-off time, lead time, dispatch day and credit
limit all produce a warning, shown live in the order form and stored on
the order in `b2b_order_terms.warnings_json`. Nothing is refused. A home
bakery's exception rate is high enough that a hard block would be worked
around by phoning in the order — which loses the record entirely. The
human stays in the loop, and the warning is on the order forever.

**5. Production is shared, with a recorded switch for later.**

Partners receive finished goods only and bake on the same line as retail.
`b2b_accounts.production_mode` (`SHARED` / `DEDICATED`) is copied onto
each order's terms row at creation, so introducing a dedicated line later
is a behaviour change on new orders and a report dimension on old ones —
not a data migration. Semi-finished supply (sponges, ganache) is
explicitly out of scope until there is a production line to model.

**6. A partner owns one `Customer` row.**

`orders.customer_id` is `NOT NULL`, and every downstream feature (invoice
snapshot, WhatsApp messages, statements) already works off a customer.
Creating the billing customer when the account is created — and reusing
an existing customer with the same phone — avoids changing that
constraint for everyone.

## Consequences

- (+) Retail is untouched: a retail order has `channel='RETAIL'`,
  `account_id=NULL`, retail prices, and no extra screen.
- (+) One pipeline: a B2B order appears in Today's dispatch, deducts
  stock, and carries COGS exactly like a retail order.
- (+) Both commercial models are data, not code — a partner switching
  from unit price to commission is a new contract row.
- (+) Price history is immutable: contract + slab + snapshot.
- (−) Two pricing semantics exist in one system, and the order form has a
  channel toggle. Both are documented here and covered by tests
  (`tests/test_b2b.py`).
- (−) `orders.account_id` is added without a database-level foreign key on
  SQLite (a rebuild would drop the `status` CHECK constraint). The ORM
  still declares it, accounts are soft-deleted, and a fresh database
  created by `create_all` has the constraint.
- (−) Credit is computed from unpaid invoices on demand rather than kept
  as a balance column. At a few hundred orders a year that is free; if
  the ledger ever gets big, it becomes a view.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Separate `b2b_orders` table | Duplicates production, stock, COGS and invoicing — the code most likely to drift |
| Channel only in a side table (no columns on `orders`) | Every list, report and dashboard needs a `LEFT JOIN` to answer "retail or B2B" |
| Wholesale price written into `products.base_price` | Destroys the retail price and reprices history |
| Hard block on credit limit | Phone orders bypass it; the record is lost, which is worse than a late payment |
| Commission modelled as a negative line item | Pollutes revenue, GST and COGS reporting |
