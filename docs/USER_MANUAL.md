# 🧁 House of Desserts — User Manual

A complete walkthrough of every screen, control, and data relationship.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Today — the home screen](#2-today--the-home-screen)
3. [Dashboard](#3-dashboard)
4. [Products](#4-products)
5. [Customers](#5-customers)
6. [Orders](#6-orders)
7. [B2B partners](#7-b2b-partners)
8. [Invoices](#8-invoices)
9. [Export](#9-export)
10. [Audit Log](#10-audit-log)
11. [Settings](#11-settings)
12. [Data Relationships](#12-data-relationships)
13. [FAQ & Troubleshooting](#13-faq--troubleshooting)

> Deep-dive training material lives in [`docs/training/`](training/README.md).
> The B2B module has its own guide: [b2b-partners.md](training/b2b-partners.md).

---

## 1. Getting Started

### First-Time Setup

Before using the app, ensure:

1. **Add your products** — Go to 🎂 Products → "Add Product". Add at least one item (name, SKU, price, GST rate).
2. **Add your customers** — Go to 👥 Customers → "Add Customer". Add the person placing the order.
3. **Create an order** — Go to 📋 Orders → "New Order". Select customer, add items, record advance.

### Navigation

The top navbar contains all sections. On mobile, only icons are shown (tap to navigate). On desktop, icon + text.

| Icon | Section | What it does |
|------|---------|-------------|
| 📊 | Dashboard | Today's stats, recent orders |
| 🎂 | Products | Manage your product catalog |
| 👥 | Customers | Manage customer records + addresses |
| 📋 | Orders | Create, track, and manage orders |
| 📥 | Export | Download CSV/JSON for tax filing |
| 📜 | Audit | View all system changes (read-only) |

The **logo** (top-left) always takes you back to the Dashboard.

On mobile, a floating **"+"** button (bottom-right) takes you directly to "New Order".

---

## 2. Today — the home screen

**URL:** `/today` (also what `/` redirects to)

This is the screen the bakery actually opens first thing in the morning.
It answers three questions: what is going out today, what do I need to
bake, and what am I short of.

### Low stock (top, only when relevant)

Appears only if an ingredient is at or below its reorder threshold.
Columns: ingredient, on hand, threshold, short by. Sorted by the biggest
shortfall first. **Manage inventory** jumps to the ingredients list.

### Dispatch — Today

Every non-cancelled order whose fulfillment date is *today*, sorted by
time. Columns: time, order, customer (tap the phone number to call),
type (delivery/pickup), fulfillment status, payment status, balance.

Each row carries two shortcuts:

- **💬** — opens the pre-written WhatsApp message for that order.
- **Mark [next status]** — advances the order (CONFIRMED → IN PROGRESS →
  READY → DELIVERED) and reloads the page.

A B2B order shows the partner name with a small **B2B** badge instead of a
customer name.

### Production — Overdue & Next 7 Days

Ingredients and time are planned here, aggregated **by SKU**, in three
buckets:

| Bucket | Meaning |
|---|---|
| **Overdue — fulfillment date has passed** | Still CONFIRMED or IN PROGRESS after its date. Late work that must not be forgotten. |
| **Urgent — fulfilling today** | Bake these now. |
| **Tomorrow** | Prep tonight or early tomorrow. |
| **Later this week** | Everything else inside the 7-day window. |

Columns: item, quantity (total units across all orders), **fulfillment**
(the earliest date and time this SKU is needed, with the number of orders
underneath), and prep time in hours.

> An order moved *beyond* seven days does not appear here until it enters
> the window. That is deliberate — a 7-day horizon is what a production
> plan is for. Overdue orders, by contrast, stay visible until they are
> delivered or cancelled.

### The badge in the header

The unit count next to the production heading is the total number of items
in the window, including overdue work.

---

## 3. Dashboard

**URL:** `/`

### What you see

- **4 stat cards** (top row):
  - **Today's Orders** — count of orders created today
  - **Pending Delivery** — count of orders in "READY" status
  - **Outstanding Balance** — total unpaid amount across all active orders
  - **Total Products** — count of active products in catalog

- **Recent Orders table** (below cards):
  - Shows last 10 orders with: Order #, Customer name, Status badge, Amount, Date
  - Click "View All →" to go to the full Orders page

### Status Badge Colors

| Status | Color | Meaning |
|--------|-------|---------|
| INQUIRY | Grey | Customer asked, not yet confirmed |
| CONFIRMED | Blue | You accepted the order |
| IN_PROGRESS | Yellow | You're baking/preparing |
| READY | Green | Ready for pickup/delivery |
| DELIVERED | Green | Customer received it — the successful end of fulfillment |
| CANCELLED | Red | Order was cancelled |

> There is **no PAID status**. Whether an order is paid is a separate
> axis, shown by its own **Payment: Paid / Partial / Unpaid** badge.

---

## 4. Products

**URL:** `/products`

### Product List

Displays all products as **cards** in a grid. Each card shows:
- Name, SKU (monospace font)
- Category badge, HSN code badge, GST rate badge
- Price (bold, bottom-left)
- Active/Inactive status badge
- **Edit** and **Delete** buttons

### Add Product

Click **"+ Add Product"** (top-right). Fill in:

| Field | Required | Example | Notes |
|-------|----------|---------|-------|
| Name | ✅ | Choco Truffle Cake | Display name |
| SKU | ✅ | CHOC-TRUFFLE-500G | Must be unique. Your internal code. |
| HSN Code | No (default 1905) | 1905 | For GST. Cakes = 1905. |
| Category | No (default Cake) | Cake, Bread, Cookie, Pastry | Grouping label |
| Base Price | ✅ | 500.00 | Price before GST |
| GST Rate | No (default 5%) | 5, 0, 12, 18 | Percentage |
| Prep Time | No (default 4) | 4 | Hours needed to prepare |
| Description | No | Rich chocolate truffle... | Shown on invoices |
| Active | ✅ (checked) | — | Uncheck to hide from orders |

### Edit Product

Click **Edit** on a product card. Same form, pre-filled. Change any field → Save.

### Delete Product

Click **Delete** → confirm. Product is **soft-deleted** (marked inactive). It disappears from the order form's type-ahead but remains in historical orders.

---

## 5. Customers

**URL:** `/customers`

### Customer List

Table view showing: Name, Phone, Email, Order count, Since date, Actions.
- Soft-deleted customers appear at 40% opacity with a "Deleted" badge.
- Active customers have **Edit** and **Delete** buttons.

### Add Customer

Click **"+ Add Customer"**. Fill in:

**Customer Details section:**

| Field | Required | Notes |
|-------|----------|-------|
| Full Name | ✅ | |
| Phone | ✅ | Must be unique among active customers |
| Email | No | |
| Notes | No | Allergies, preferences, etc. |

**Addresses section:**

You can add **multiple addresses** at once:
- Each row has: **Label** (narrow, e.g., "Home") + **Address line** (wide) + **Def** toggle
- Click **"+ Add Address"** to add more rows
- Only ONE address can be marked "Def" (default). Toggling one ON automatically turns others OFF (instant, in the browser).
- The default address is auto-filled when this customer is selected in an order.

### Edit Customer

Click **Edit** on a customer row. Same form as Add, but:
- Existing addresses are shown as **editable rows** (label + line inputs, pre-filled)
- Each has a **Def toggle** (amber when ON) and a **✕** button (soft-deletes that address)
- You can still add new addresses below the existing ones
- Clicking the **Def toggle** on an existing address immediately makes it the default (AJAX, page reloads)

### Customer Detail (Read-Only)

Click a customer's **name** in the list. Shows:
- Customer details (disabled inputs, same layout as edit form)
- Addresses (read-only, with disabled Def toggles)
- **Order History** table (all past orders with status, amount, balance)
- **Edit** button (top-right) → goes to edit form
- **Delete** button (top-right) → soft-deletes customer + all their addresses

### Search (in Order Form)

Both pickers in the order form are **type-aheads**, not dropdowns:

| Field | Type | Matches on | Shows |
|---|---|---|---|
| Customer | 2+ characters | name (any case) or phone (partial) | name, phone, address count |
| Product | 2+ characters | name, SKU or category | name, SKU, measure/pack, price |

Tap a result to select it. Editing the text afterwards clears the
selection, so you cannot accidentally submit a half-typed name. The
customer's default address fills the delivery field when Delivery is
chosen.

---

## 6. Orders

**URL:** `/orders`

### Order List

Cards showing: Order #, Customer, Date, Status badge, Amount, Balance (if any).

**Filter tabs** (top): All | Confirmed | In Progress | Ready | Delivered

**Quick actions** (on each card):
- **"→ Mark [Next Status]"** button — advances the order one step
- **"Cancel"** button — cancels the order (with confirmation)

### Order Lifecycle
```
INQUIRY → CONFIRMED → IN_PROGRESS → READY → DELIVERED
↘ CANCELLED (from any state before DELIVERED)
```

- You **cannot** skip states (e.g., can't go CONFIRMED → READY directly)
- **DELIVERED** is the final fulfillment step — the order is with the customer.
- **Payment is separate.** Whether the customer has paid is shown by the **Payment: Paid / Partial / Unpaid** badge. Recording a payment never advances fulfillment, and delivering never changes the payment state.
- **CANCELLED** is a terminal state (can't un-cancel)

### New Order

Click **"+ New Order"** (or the mobile FAB "+").

The form is five cards, top to bottom: **Customer**, **Fulfillment**,
**Items**, **Advance**, **Notes**. (A B2B order inserts a **Partner
terms** card and a **Partner pricing** panel — see §7.)

**Customer**

| Field | How it works |
|-------|-------------|
| Retail / B2B toggle | Top-right of the card. Retail is the default. |
| Customer | **Type-ahead**: type 2+ characters of a name or phone, tap a result. A hidden id is stored — the visible text is just a label. |
| + New Customer | Opens a mini form (name, phone, email, address) without leaving the order. |

**Fulfillment**

| Field | How it works |
|-------|-------------|
| Type | Pickup (default) or Delivery. Delivery reveals the address box. |
| Order placed on | Pre-filled with today. Editable. |
| Ready by / Fulfillment time | **Required.** Defaults to tomorrow 12:00. Orders are sorted by this everywhere. |
| Delivery address | Auto-filled from the customer's default address when Delivery is chosen; type over it freely. Hidden for Pickup. |

**Items**

- One empty row to start; **+ Add item** clones it.
- Each row: **product type-ahead** (name or SKU, 2+ characters, tap a
  result) + **Qty** + **Remove**.
- Under a chosen product you see its price, e.g. `₹850.00`.
- The form refuses to submit while a row has text but no product chosen —
  pick from the list rather than typing a name.

**Advance** — amount received (0 if none) and the method (Cash / UPI /
Bank / Card). Recording an advance creates a payment immediately; it does
not change the fulfillment status.

**Notes** — free text: cake message, allergies, instructions.

**Submit:** **Create Order** → you land on the order detail page.

### Order Detail

**URL:** `/orders/{id}`

Shows:
- **Header:** Order #, Customer, Date, Status badge
- **Status actions:** "Mark [Next Status]" + "Cancel" buttons
- **Invoice actions:** "View Invoice" + "Print Receipt" buttons
- **Items table:** Product, SKU, Qty, Unit Price, Total, Notes
- **Payments section:** All payments recorded + "Record Payment" form (if balance > 0)
- **Delivery info:** Address + date (if delivery type)

**Recording a Payment:**
- Amount (pre-filled with remaining balance)
- Method (UPI/Cash/Bank)
- Reference (optional — UPI transaction ID, etc.)
- Click "Record" → balance updates and the **Payment** badge changes (Paid / Partial / Unpaid). The fulfillment status is not affected.

### Editing Orders

**Edit** appears on the order detail page while the order is **CONFIRMED**.
You can change the fulfillment time, delivery type and address, the notes,
and the items. Things to know:

- Payments already recorded are never touched.
- The order total cannot be reduced below what has already been paid.
- Every change is written to the audit log with old and new values.
- If an invoice has already been issued, editing the order does **not**
  change that invoice — it is a snapshot.
- Once the order moves to IN PROGRESS it is locked. Cancel and recreate,
  or note the change in the order.

A B2B order is re-priced from the partner's contract on every edit, so a
line added later picks up the right rate.

---

## 7. B2B partners

**URL:** `/b2b`

Selling to shops and franchisees. This section is a summary — the full
training guide, with screenshots, worked examples and troubleshooting, is
[`docs/training/b2b-partners.md`](training/b2b-partners.md).

### When to use it

Another *business* buying on agreed terms: a café, a sweet shop, a
franchisee, a distributor. Not a retail customer who happens to order
often — keep those as customers.

### The pieces

| Piece | What it holds |
|---|---|
| **Partner** | The shop: code, contact, GSTIN, credit days, credit limit, minimum order, cut-off, lead time, dispatch days |
| **Contract** | Dated envelope for prices. Versioned — never edit one that has orders; close it and open a new one |
| **Price list** | Product + "from quantity" + rate, or a commission percentage |
| **B2B order** | A normal order that uses the partner's prices instead of retail ones |

### Two pricing models

- **Unit price** — an agreed rate per product, optionally cheaper at
  volume (e.g. ₹780 each, ₹740 from 10 up).
- **Commission** — the partner sells at your MRP and keeps a cut; you
  invoice MRP minus that cut (e.g. MRP ₹540 − 35% = ₹351).

A contract uses one model by default, and any product can override it.

### Taking a B2B order

`/orders/new` → flip the toggle at the top of the Customer card from
**Retail** to **B2B partner** → search the shop → fill the **Partner
terms** card (PO reference, payment terms, dispatch date) → add items as
usual.

A **Partner pricing** panel appears and updates as you type, showing each
line's rate, its source (*Contract price (10+)*, *MRP less 35%
commission*, or *Retail price*), the total, and any warnings.

### What is different from retail

| | Retail | B2B |
|---|---|---|
| Number | `HOD-2026-0001` | `HOD-B2B-2026-0001` |
| Price | product's retail price | contract price |
| Invoice | customer | partner, with GSTIN and PO reference |
| Checks | none | minimum order, cut-off, lead time, dispatch day, credit limit — **warnings only, never blocks** |
| Production | shared line | shared line (a dedicated line is a per-partner flag for later) |

Everything else — statuses, ingredient deduction, COGS, WhatsApp
messages, reports — is identical.

### Credit

**Outstanding** is the sum of unpaid balances across a partner's open
orders, recomputed every time you look. There is no separate ledger.
Exceeding the credit limit turns the amount red on the partners list and
on the partner page, and adds a warning to the order — it does not block
anything.

**Partner page → Statement** gives billed / received / outstanding plus
one row per order, downloadable as CSV for the monthly chase.

---

## 8. Costing & Pricing

The app can tell you what a product **costs to make** and what you should
**charge for it**. It needs two things first: what your ingredients cost,
and what goes into each product.

### 8.1 Enter ingredients

**Costing → Bulk entry**, first box. One line per ingredient:

```
Dark chocolate, g, 0.45
Butter, g, 0.55
Sugar, g, 0.045
Eggs, no, 7
```

`name, unit, cost per unit` — the cost is for **one** unit, so ₹0.45 for a
gram of chocolate, not ₹450 for a kilo. This is the single most common
mistake, and it makes every cost on the sheet wrong.

### 8.2 Enter a recipe

Second box on the same page:

```
Nutella Brownie, Dark chocolate, 1200, 24
Nutella Brownie, Butter, 800, 24
```

`family, ingredient, quantity, batch yield`. The last column is optional and
defaults to 24. The quantity is in the ingredient's own unit — grams for
chocolate, a count for eggs.

**One recipe per product, not per size.** A recipe describes a *batch* —
one tray of 24 brownies. Every size is costed from it automatically: the
9-piece box is that batch divided by 24 and multiplied by 9. Adding a
12-piece box later costs nothing.

Both boxes are **all or nothing**: if one line is wrong, nothing is saved
and the page tells you which line.

### 8.3 Read the cost sheet

**Costing →** tap a product. The sheet shows:

| Line | What it is |
|---|---|
| Material | ingredients, scaled from the batch to this size |
| Packaging | set per size on the same page — a 9-piece box is one box |
| Labour | the batch's minutes ÷ yield × pieces, at your hourly rate |
| Overhead | electricity, gas, depreciation for the batch, scaled |
| Wastage | spoilage and trim, as a % of material + labour |
| **Total cost** | what one of these actually costs you |

Below it: the selling price, the gross margin in rupees and as a
percentage, the markup, and the break-even price.

**If a product has no recipe, the sheet says the cost is unknown — not
zero.** A zero would read as a 100% margin, which is a lie.

### 8.4 Choose a price

The sheet offers three routes, side by side:

| Method | Means |
|---|---|
| **40% margin** | 40% of the *price* is profit |
| **50% markup** | 50% on top of *cost* — which is only a 33% margin |
| **At the price you charge** | take your current price and see what it yields |

Margin and markup are **not the same number**, and mixing them is the most
expensive mistake in this trade. A 50% markup earns a 33.3% margin.

Prices are rounded **up** to ₹5 or ₹10 (Costing → Assumptions). Never down —
rounding down to make a price tidy gives away margin on every sale.

Nothing changes a price by itself. Pressing **Use** writes the new price and
records it in the audit log.

### 8.5 Assumptions

**Costing → Assumptions** holds the numbers used everywhere: labour rate per
hour, default wastage, target margin, whether prices are before or after
GST, and how suggestions are rounded.

If you are not registered for GST, the rate is zero and the sheet says so —
including what the customer would pay at 5%, which is the price list you
will need the day you register.

### 8.6 Two different margins — do not confuse them

| Margin | Means | Where |
|---|---|---|
| **Recipe margin** | price − (material + labour + overhead + wastage), at today's costs | Costing screens |
| **Reported margin** | revenue − cost actually booked from stock | Monthly report |

They will differ, and both are right: one is a planning number, the other is
what the books recorded.

---

## 9. Invoices

### Viewing an Invoice

From the order detail page, click **"View Invoice"**.

Shows a styled on-screen preview:
- **Header:** Your business name, address, FSSAI, GSTIN (if set)
- **Bill To:** Customer name, phone, email, default address
- **Deliver To** (or **Pickup**): Delivery address + date
- **Items table:** #, Item, HSN, Qty, Rate, GST, Amount
- **Totals:** Subtotal, CGST + SGST (if registered), Total, Paid, Balance

**Actions:**
- **"Download PDF"** → browser downloads the invoice as a PDF file
- **"Print Receipt"** → sends to thermal printer (or saves to file if `PRINTER_TYPE=file`)

### GST Display Rules

| Your GSTIN in .env | What the invoice shows |
|-------------------|----------------------|
| Blank (not registered) | No GST lines. Just Subtotal + Total. |
| Filled in (registered) | CGST @ X% + SGST @ X% (split 50/50 of the product's GST rate) |

### PDF File Location

Generated PDFs are saved to `data/invoices/` with the invoice number as filename (e.g., `HOD-2026-0001.pdf`).

### Thermal Receipt

Printed on 80mm (or 58mm) roll paper. Shows:
- Business name, address, phone, FSSAI
- Invoice number, date, customer, delivery info
- Itemized list with quantities and amounts
- Subtotal, GST (if registered), Total, Paid, Balance
- "Thank you" footer

---

## 10. Export

**URL:** `/export`

### How to Use

1. Pick a **From Date** and **To Date** (date pickers)
2. Click one of the three download buttons:

| Button | What you get | Use case |
|--------|-------------|----------|
| **Orders CSV** | One row per order: number, date, customer, phone, status, delivery type, totals, items | Monthly review, ITR |
| **Payments CSV** | One row per payment: order #, customer, date, amount, method, reference | Bank reconciliation |
| **Summary JSON** | Aggregated stats: total orders, revenue, GST collected, outstanding, top products | Quick overview for CA |

### CSV Format

Opens directly in Excel. Columns are comma-separated. Use for:
- Filing ITR (income = sum of "Total Amount" column)
- Showing your CA the monthly business activity
- Tracking which products sell most

---

## 11. Audit Log

**URL:** `/audit`

### What it shows

A chronological table of **every significant action**:

| Column | Meaning |
|--------|---------|
| Time | When it happened |
| Entity | What was changed (e.g., "Order#3", "Customer#1") |
| Action | CREATE / UPDATE / DELETE / STATUS_CHANGE / PAYMENT |
| Details | JSON of old/new values |

### Filter Tabs

All | Orders | Payments | Customers | Products

### What gets logged

| Action | Logged as |
|--------|-----------|
| Create a product | Product#1 CREATE |
| Edit a product | Product#1 UPDATE |
| Delete a product | Product#1 DELETE |
| Create a customer | Customer#1 CREATE |
| Edit a customer | Customer#1 UPDATE |
| Delete a customer | Customer#1 DELETE |
| Create an order | Order#1 CREATE |
| Change order status | Order#1 STATUS_CHANGE |
| Record a payment | Payment#1 PAYMENT |
| Delete an address | Address#1 DELETE |

### Purpose

- **Financial transparency:** Prove what was sold, when, and for how much
- **Dispute resolution:** "Did I change that price?" → Check the log
- **CA audit:** Show a complete trail of all transactions

---

## 12. Settings

**URL:** `/settings`

### What it shows

Read-only display of all business configuration:
- Business name, tagline, phone, email, address
- FSSAI number, GSTIN
- Printer type and paper width
- Invoice prefix and start number

### How to Change

Edit the `.env` file in the project root. Restart the server.

Example `.env`:
```env
APP_NAME=House of Desserts
FSSAI_NUMBER=10012345678901
GSTIN=
PHONE=+91 98765 43210   
```

## 13. Data Relationships
```mermaid
┌──────────────┐       ┌──────────────┐
│  CUSTOMERS   │       │  ADDRESSES   │
│──────────────│       │──────────────│
│ id (PK)      │──1:N──│ id (PK)      │
│ name         │       │ customer_id  │──FK→ customers.id
│ phone (UQ)   │       │ label        │
│ email        │       │ line         │
│ notes        │       │ is_default   │
│ is_active    │       │ is_active    │
└──────┬───────┘       └──────────────┘
       │
       │ 1:N
       ▼
┌──────────────┐       ┌──────────────┐
│    ORDERS    │       │ ORDER_ITEMS  │
│──────────────│       │──────────────│
│ id (PK)      │──1:N──│ id (PK)      │
│ order_number │       │ order_id     │──FK→ orders.id
│ customer_id  │──FK───│ product_id   │──FK→ products.id
│ status       │       │ quantity     │
│ order_date   │       │ unit_price   │
│ delivery_type│       │ gst_amount   │
│ delivery_date│       │ line_total   │
│ delivery_addr│       │ customization│
│ total_amount │       └──────────────┘
│ advance_paid │
│ balance_due  │       ┌──────────────┐
│ is_active    │──1:N──│  PAYMENTS    │
└──────────────┘       │──────────────│
                       │ id (PK)      │
                       │ order_id     │──FK→ orders.id
                       │ amount       │
                       │ method       │
                       │ reference    │
                       │ received_at  │
                       └──────────────┘

┌──────────────┐       ┌──────────────┐
│  PRODUCTS    │       │  INVOICES    │
│──────────────│       │──────────────│
│ id (PK)      │       │ id (PK)      │
│ sku (UQ)     │       │ order_id     │──FK→ orders.id (1:1)
│ hsn_code     │       │ invoice_number│
│ name         │       │ invoice_date │
│ category     │       │ status       │
│ base_price   │       │ pdf_path     │
│ gst_rate     │       └──────────────┘
│ prep_time    │
│ is_active    │       ┌──────────────┐
└──────────────┘       │  AUDIT_LOG   │
                       │──────────────│
                       │ id (PK)      │
                       │ entity_type  │
                       │ entity_id    │
                       │ action       │
                       │ old_value    │
                       │ new_value    │
                       │ changed_at   │
                       └──────────────┘   
```
### Key Relationships
| From | To | Type | Meaning |
|------|-----|------|---------|
| Customer | Address | 1:N | One customer has many addresses |
| Customer | Order | 1:N | One customer places many orders |
| Order | OrderItem | 1:N | One order has many line items |
| OrderItem | Product | N:1 | Each line item references one product |
| Order | Payment | 1:N | One order can have multiple payments |
| Order | Invoice | 1:1 | One order has at most one invoice |
| Product | OrderItem | 1:N | One product appears in many order items |

### Soft Delete Behavior
| Entity | What happens on delete |
|--------|----------------------|
| Customer | `is_active=False`. All their addresses also `is_active=False`. Orders remain intact. |
| Product | `is_active=False`. Disappears from order form. Historical orders still show the product name. |
| Address | `is_active=False`. Disappears from dropdowns. Order's `delivery_address` text is unaffected. |
| Order | **Never deleted.** Only status changes to CANCELLED. |
| Payment | **Never deleted.** Immutable financial record. |
| Invoice | **Never deleted.** Immutable financial record. |

## 14. FAQ & Troubleshooting
#### "Why can't I select a customer in the order form?"
You need at least 2 characters in the search box. Also, the customer must be active (not deleted).

#### "Why is the delivery address field greyed out?"
You selected "Pickup" as the delivery type. Switch to "Delivery" to enable it.

#### "Why doesn't the customer's address auto-fill?"
The customer must have at least one active address saved. Go to their Edit page → add an address → mark it as Default.

#### "I deleted a customer but their orders still show their name."
Correct behavior. Orders store the customer's name at the time of order. Soft-deleting the customer doesn't modify historical orders.

#### "The PDF shows 'Rs.' instead of '₹'."
The Noto Sans font file isn't in app/static/fonts/. Either download it (see SETUP.md) or accept "Rs." as the display.

#### "How do I change my business name?"
Edit APP_NAME in the .env file → restart the server.

#### "How do I backdate an order?"
When creating a new order, change the "Order Date" field to the earlier date.

#### "Can I undo a status change?"
Not directly. The audit log records the change. If you need to revert, you'd need to manually update the DB or add a "revert" feature.

#### "The thermal printer isn't printing."
Check: 
- (1) PRINTER_TYPE in .env matches your setup, 
- (2) printer is connected and on, (3) for file type, check data/receipt_preview.bin was created.