# What's new

Every release, newest first. The app reads this file directly — the page at
**More → System → What's new** is this document, so there is one list and
not two.

Versions were assigned at release time. The first deployment is **v1.0**;
everything before it was built but not running.

---

## v1.5 — 26 November 2026

### Added
- **Estimate a new product** — cost something before it exists. Enter a
  batch, get the cost and three prices, save nothing. Press *Create the
  product* to commit it with the recipe and price already attached.
- **What's new** — this page.

### Fixed
- The Costing screen shipped with no navigation link, so the module was
  unreachable from inside the app.
- The More menu listed links in build order. Now grouped by purpose:
  Selling, Making, Numbers, System.
- The Ready-stock entry carried button styling inside the dropdown, which
  broke the column alignment. Labels now sit on one line.

---

## v1.4 — 26 November 2026

### Added
- **Costing & pricing.** A recipe per product family with a batch yield,
  so one brownie recipe costs every box size. Material, packaging, labour,
  overhead and wastage, each shown separately.
- **Three pricing methods** side by side: target margin, markup, and what
  your current price actually yields. A 50% markup is a 33% margin, and
  the screen says so.
- **Bulk entry** for ingredients and recipes, so a catalogue can be loaded
  in one paste instead of fifty forms.
- **Costing assumptions** — labour rate, default wastage, target margin,
  GST mode and price rounding.

### Changed
- The product list now shows the **real margin**, not an ingredient-only
  figure. A product with no recipe reads "not costed" rather than 100%.
- Prices are only ever rounded **up**. Rounding down to look tidy gives
  away margin on every sale.

### Under the hood
- The service layer no longer depends on the web framework. Business rules
  raise domain errors; one handler turns them into status codes. A test
  blocks FastAPI from the domain package at import time.
- Two pure modules — the cost calculator and the pricing rules — at 100%
  coverage, including property-based tests.

---

## v1.3 — 23 November 2026

### Added
- **Product sizes as a family.** One recipe and one identity per product,
  five sizes under it. The picker shows `Nutella Brownie · 9 pc`.
- **Bulk product import** — paste rows and the catalogue lands at once.
- **One screen to label every size**, with the other sizes shown as chips.

---

## v1.2 — 23 November 2026

### Added
- **Ready stock** — bake ahead of orders for walk-ins and urgent asks.
  An order takes from the shelf first and only bakes the shortfall.
- **Cost follows the goods** — units carry their cost from the oven, so
  the cost lands in the month that sold them, not the month that baked.

---

## v1.1 — 23 November 2026

### Added
- **Selling above or below list** — a rate per line, with the list price
  kept beside it so the difference is visible.
- **Cash reconciliation** in the monthly report: opening outstanding +
  revenue − cash received = closing outstanding, which always ties.

### Fixed
- Cancelled orders kept a balance nobody owed. Cancelling now clears it.
- The report booked every status except cancelled as revenue, so an unpaid
  order would have counted as income.

---

## v1.0 — 21 November 2026

The first deployment. The system as it went live:

### Orders & customers
- Retail orders with items, quantities, packaging and customisation notes.
- Customer records with multiple addresses and a default.
- A status flow from enquiry to delivered, with guarded transitions.

### Money
- Payments, part-payments and balances.
- Invoices with a number series, printable and downloadable as PDF.
- GST per line, at the rate set on each product.

### Production & stock
- Ingredients with a stock ledger — purchases, consumption, wastage.
- Recipes per product, and a "can I make this?" capacity check.
- A Today page with the day's orders and an overdue production bucket.

### Business-to-business
- Partner accounts, contracts and price lists.
- Two pricing modes: per unit, or commission on the partner's sale.
- Credit limits that warn rather than block — a human decides.
- Partner statements, and margin per partner.

### Reporting
- Monthly report as PDF and CSV: revenue, GST, cost of goods, margin,
  top products, channel split.
- Order and payment exports.

### System
- Every change written to an audit log with the old and new value.
- Settings for the shop's name, address, GSTIN and messages.
- Nightly backups, retained 31 days.
- One-command deployment with a pre-flight check, a verified backup, a
  migration step, six health checks and automatic rollback.
