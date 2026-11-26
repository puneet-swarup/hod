# What's new

What the app can now do, newest first — written for the person running the
bakery, not for the person who wrote the code. Every entry is something you
can go and use today.

The page at **More → System → What's new** reads this file directly, so
there is one list and not two.

Versions are assigned when a release ships. The first deployment is **v1.0**;
everything before it was built but not running.

---

## v1.5 — 26 November 2026

### Added
- **Estimate a new product before you make it.** Enter a batch — what goes
  in, how long it takes, what the packaging costs — and see what one would
  cost and what to charge, without creating anything. If the numbers work,
  one button turns the estimate into a real product with its recipe and
  price already in place.
- **What's new** — this page, so you can see when something arrived.

### Fixed
- **Costing was unreachable.** The screens existed but there was no link to
  them anywhere in the app.
- **The More menu was in build order.** It is now grouped by what you are
  doing: Selling, Making, Numbers, System.
- **Ready stock sat out of line** in the menu, with a stray button style
  that pushed it out of step. Every entry now lines up.

---

## v1.4 — 26 November 2026

### Added
- **Costing and pricing.** Enter what goes into a product once, and the app
  tells you what it costs to make — ingredients, packaging, labour,
  electricity and wastage, each shown separately — and what to charge.
- **One recipe covers every size.** A recipe describes a batch, so a tray
  of 24 brownies prices the 1-piece, the 4-piece and the 9-piece box
  without entering anything three times. A new size later costs nothing.
- **Three ways to set a price**, side by side: the margin you want, a
  markup on cost, or the price you already charge with what it earns you.
  A 50% markup is a 33% margin, and the screen says so plainly.
- **Load your catalogue in one paste.** Ingredients and recipes can be
  pasted in bulk instead of typed one form at a time.
- **Your own assumptions** — what an hour in the kitchen is worth, how much
  you expect to lose to spoilage, the margin you aim for, and whether your
  prices include tax.

### Changed
- **The product list shows the real margin**, not just what the ingredients
  cost. A product with no recipe now reads "not costed" instead of
  pretending to earn 100%.
- **Suggested prices round up, never down.** A tidier price that is lower
  gives away money on every sale.

---

## v1.3 — 23 November 2026

### Added
- **Sizes belong to one product.** A brownie sold as 1, 2, 4, 6 and 9
  pieces is one product with five sizes, not five separate products. The
  order form shows `Nutella Brownie · 9 pc` so the right one is obvious.
- **Load products in one paste** — the whole catalogue at once, with sizes
  grouped automatically.
- **Label every size on one screen**, with the other sizes shown beside it.

---

## v1.2 — 23 November 2026

### Added
- **Ready stock.** Bake ahead of orders for walk-ins and urgent asks, and
  answer "what's ready right now?" from one screen. An order takes from the
  shelf first and only bakes what is missing, so nothing is counted twice.
- **What the shelf is worth** — units on hand and their cost, not just a
  count.

### Changed
- **Cost now follows the goods.** Units carry their cost from the oven to
  the customer, so the cost lands in the month you sold them rather than
  the month you baked them. Gross margin in the monthly report means
  something again.

---

## v1.1 — 23 November 2026

### Added
- **Sell above or below your list price** — a festival price, a discount or
  a one-off — with the list price kept beside it so the difference is
  visible on the order and in the report.
- **The month reconciles.** The report now separates what you earned from
  what actually arrived, and shows the bridge: opening outstanding +
  revenue − cash received = closing outstanding. It ties, every month.
- **Money held on cancelled orders** is shown rather than disappearing.

### Fixed
- **Cancelled orders showed a balance nobody owed.** Cancelling now clears
  it, and keeps the record of the cash you did take.
- **An unpaid order would have counted as income.** The report treated
  every status except cancelled as revenue.

---

## v1.0 — 21 November 2026

The first deployment.

### Orders and customers
- Take orders with items, quantities, packaging and special instructions.
- Keep customers with several delivery addresses and a default.
- Follow an order from enquiry to delivered, with the steps guarded so it
  cannot jump backwards by accident.

### Money
- Record payments, part-payments and balances.
- Issue invoices with their own number series, printable and downloadable.
- Charge tax per line, at the rate set on each product.

### Production and stock
- Track ingredients as a ledger — what you bought, what you used, what was
  wasted — so stock is always the sum of what happened.
- Keep a recipe per product and see at a glance whether you can make it.
- Start the day on a Today page: what is due, and what is running late.

### Business customers
- Manage partner accounts, contracts and their own price lists.
- Charge them per unit, or take a commission on their sale.
- Set a credit limit that warns rather than blocks — a person decides.
- Send a partner a statement, and see the margin you make on each one.

### Reports
- A monthly report as PDF and CSV: revenue, tax, cost of goods, margin,
  best sellers, and how much came from business customers.
- Export orders and payments to a spreadsheet.

### Running the business
- Every change recorded with what it was before and what it became.
- Your shop's name, address, tax number and message templates in one place.
- Nightly backups, kept for a month.
- One command to update the app: it takes a backup first, checks that
  everything still works, and undoes itself if anything does not.
