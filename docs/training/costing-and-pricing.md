# Costing & pricing

How to find out what a product actually costs you, and what to charge for it.

---

## Before you start: the one mistake that ruins everything

The app asks for the cost of **one unit** of an ingredient.

| Ingredient bought as | Enter |
|---|---|
| 1 kg chocolate for ₹450 | `450 ÷ 1000 = 0.45` |
| 500 g butter for ₹275 | `275 ÷ 500 = 0.55` |
| 1 dozen eggs for ₹84 | `84 ÷ 12 = 7` |

If you enter 450 instead of 0.45, every cost on every sheet is a thousand
times too high, and every suggested price is nonsense. It is the first thing
to check when a number looks wrong.

---

## Step 1 — Enter your ingredients

**Costing → Bulk entry**, top box:

```
Dark chocolate, g, 0.45
Butter, g, 0.55
Sugar, g, 0.045
Eggs, no, 7
Maida, g, 0.04
```

`name, unit, cost per unit`

Use `g`, `ml`, `kg`, or `no` for a count. Keep them consistent with how you
weigh things.

---

## Step 2 — Enter a recipe

Second box on the same page:

```
Nutella Brownie, Dark chocolate, 1200, 24
Nutella Brownie, Butter, 800, 24
Nutella Brownie, Sugar, 600, 24
Nutella Brownie, Eggs, 12, 24
Nutella Brownie, Maida, 300, 24
Nutella Brownie, Nutella, 800, 24
Nutella Brownie, Walnuts, 200, 24
```

`family, ingredient, quantity, batch yield`

- **family** is the product name, exactly as it appears in Products.
- **quantity** is how much goes into the *whole batch*, in the ingredient's unit.
- **batch yield** is how many pieces that batch makes. Leave it off and it
  assumes 24.

### Why a batch, not one piece

You bake a tray of 24. The app costs the tray and divides. That means:

- one recipe covers every size of that product
- a 9-piece box costs the tray ÷ 24 × 9
- adding a 12-piece box later needs no new recipe

---

## Step 3 — Read the sheet

**Costing →** tap a product.

```
Material      ₹595.13      ingredients, scaled to this size
Packaging     ₹ 35.00      set per size, further down the page
Labour        ₹ 56.25      90 min ÷ 24 × 9, at your hourly rate
Overhead      ₹ 45.00      electricity and gas for the batch, scaled
Wastage       ₹ 32.57      5% of material + labour
──────────────────────
Total cost    ₹763.94
Selling price ₹1,170.00
Gross margin  ₹406.06  (34.71%)
```

**If a product has no recipe, the sheet says the cost is unknown.** Not
zero — zero would look like a 100% profit, which is not true and not useful.

### Set the labour and overhead once per recipe

On the same sheet: minutes of work for the batch, the overhead for the batch
(electricity, gas), and a wastage percentage. Your hourly rate lives in
**Costing → Assumptions** and applies everywhere.

---

## Step 4 — Choose a price

The sheet offers three, side by side:

| Shown as | Means | On a ₹763.94 cost |
|---|---|---|
| **40% margin** | 40% of the *price* is profit | ₹1,275 |
| **50% markup** | 50% on top of the *cost* | ₹1,150 |
| **At the price you charge** | what your current price yields | ₹1,170 → 34.71% |

**A margin is not a markup.** A 50% markup earns a 33% margin. If you think
in "I double my cost", use the markup row. If you think in "I want a third
of the price to be mine", use the margin row. Do not mix them.

Press **Use** to take one. The old and new price are both written to the
audit log.

Prices round **up** to ₹5 or ₹10 — never down, because a tidier price that
is lower gives away margin on every sale.

---

## Step 5 — Keep it honest

Ingredient prices move. When they do:

1. Update the ingredient cost in **Ingredients**.
2. Every cost sheet recalculates immediately.
3. Any product whose margin has fallen below your target is worth a look.

A useful habit: once a month, open **Costing** and look at the products
sorted by margin. The ones at the bottom are either priced too low or
costing too much.

---

## Two margins, and why they differ

| Margin | Where | What it means |
|---|---|---|
| **Recipe margin** | Costing screens | price − what it should cost at today's prices |
| **Reported margin** | Monthly report | revenue − what the books actually recorded |

They will not match, and neither is wrong. The first is what you plan with;
the second is what happened. If they drift far apart for a long time, an
ingredient price has probably changed without anyone noticing.
