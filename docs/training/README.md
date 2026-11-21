# Training material

Everything needed to teach someone to run the bakery on this system, or
to remember how a screen works six months from now.

## Modules

| Module | Covers | Where |
|---|---|---|
| **Whole app, screen by screen** | Every screen, field and rule — the reference manual | [`../USER_MANUAL.md`](../USER_MANUAL.md) |
| **Selling to shops and franchisees** | Partners, contracts, price lists, B2B orders, credit, statements — with screenshots and worked examples | [`b2b-partners.md`](b2b-partners.md) |
| **Daily and monthly routines** | The two checklists that keep the data clean | [`routines.md`](routines.md) |

The user manual is the complete reference. The B2B guide is the only
module written as a standalone training session so far; the others can
follow the same shape (what it is, the words, the steps, a worked
example, troubleshooting, a routine).

## Reading order for a new person

1. **§1–3 of the user manual** — getting in, the nav bar, the Today page.
2. **Orders and customers** — 80% of the job is taking an order.
3. **Products and recipes** — needed before you can take a real order.
4. **The B2B module** — only if the bakery supplies shops.
5. **Reports and export** — once a month, with tea.

## Running a training session

A ninety-minute session that gets someone productive, using the demo
database.

### Before the session (5 minutes)

```bash
python scripts/seed_demo.py --db data/demo.db
DB_URL=sqlite:///data/demo.db SECRET_KEY=demo uvicorn app.main:app
```

That gives you five products with recipes, three partners on three
different sets of terms, and four B2B orders — one of them deliberately
over the credit limit. Nothing in it is real; it is safe to break.

> `scripts/seed_demo.py` refuses to run against a filename without
> "demo" in it, so it cannot wipe the live database by accident.

### The session

| Minutes | What | Who drives |
|---|---|---|
| 0–10 | The Today page: what the bakery does in a day, what the three cards mean | Trainer |
| 10–25 | Take a retail order end to end, including the customer and product type-aheads | Trainee |
| 25–35 | Move the order through the status flow; record a payment; open the invoice | Trainee |
| 35–50 | Add a product with a recipe; watch the margin appear | Trainee |
| 50–75 | **B2B:** open `/b2b`, walk the partner page, add a price row, take a B2B order and read the warnings | Trainer, then trainee |
| 75–85 | The statement and the credit warning — what to do when a partner is over limit | Trainer |
| 85–90 | The two routines: daily (Today, dispatch) and monthly (statement, margin) | Trainer |

### What to practise, not just read

- Typing two characters into a product field and picking from the list —
  this is the one interaction that trips people up.
- Reading a warning instead of dismissing it. Ask: *"the order is below
  their minimum — do we take it or top it up?"*
- Finding an order by phone number, by order number and by customer name.
- Reading a statement aloud: billed, received, outstanding.

## Conventions used in these guides

- **Bold** is a button or a field label you will see on screen.
- `mono` is something you type, or a code like `SWEET-BAN`.
- Screenshots are 390 px wide — the phone the bakery actually uses.
- Every guide ends with a troubleshooting table and a routine checklist.
