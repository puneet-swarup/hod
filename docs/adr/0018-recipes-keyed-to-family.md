# 0018 — Recipes keyed to a product family, not to a product

**Status:** Proposed
**Date:** 2026-11-26
**Deciders:** Owner
**Related:** [0016](0016-b2b-channel-additive-layer.md), [`docs/ENGINEERING_STANDARDS.md`](../ENGINEERING_STANDARDS.md), [`docs/design/costing-and-pricing-module.md`](../design/costing-and-pricing-module.md)

---

## Context

The app can already store a bill of materials: `product_ingredients` links
one product row to ingredients with a per-unit quantity, and
`recipe_service.recipe_cost()` sums it. It counts ingredients only.

Two facts about the real catalogue make that shape unusable:

1. **53 sellable items across 24 products.** A brownie is sold as 1, 2, 4,
   6 and 9 pieces — five product rows with one name. Keyed per product, that
   is five recipes for one brownie and a sixth the day a new size appears.
2. **The table is empty.** Zero ingredients, zero recipe lines. There is no
   data to migrate, and no habit to break.

The second fact is the opportunity: the schema can be chosen correctly at
zero cost. It will not be free once recipes exist.

## Options

**A. Keep recipes per product row.**
Simple, no schema change. 53 recipes to maintain, five of them differing by
a multiplier, and every new size is new data entry. Rejected: it guarantees
the module dies of maintenance.

**B. One recipe per family, with a batch yield.**
A recipe belongs to a normalised family key — the same key the size
grouping already uses. It describes one batch (24 pieces) with a labour
time and an overhead; every size computes from it by piece count.
24 recipes, new sizes free. Requires a new `recipes` / `recipe_lines`
table pair.

**C. A recipe on the family *and* per-size overrides.**
B plus an override layer for the exception cases. More powerful, more
machinery, and the exception does not exist yet.

## Decision

**Option B.** Recipes are keyed to `family_key`, carry `yield_pieces`,
`labour_minutes` and `overhead_per_batch`, and their lines live in
`recipe_lines`. Packaging cost stays per product row, because packaging does
not scale with piece count — a 9-piece box is not nine wrappers.

`recipe_service.recipe_cost()` resolves a family recipe first and falls back
to the existing per-product path, so nothing that works today breaks and the
old shape stays available for a one-off product.

Option C is deliberately not built: no product currently needs an override,
and §2 of the engineering standards says an abstraction needs two real
implementations before it is an abstraction.

## Consequences

**Good**

- 24 recipes instead of 53, and a new size costs one row, not one recipe.
- The cost of a batch is expressed once, so labour and overhead are
  computed where they actually accrue.
- The family key already exists and is already tested (the sizes feature),
  so the join is not new machinery.

**Bad**

- A family rename orphans its recipe. Mitigated: an orphaned recipe raises
  a visible warning rather than silently costing zero — a silent zero would
  show as a 100% margin, which is worse than an error.
- A product whose cost genuinely differs from its siblings (a different
  flavour, a different supplier) cannot express that without an override.
  Accepted for now; option C is the escape hatch if it appears.

**Neutral**

- `product_ingredients` is kept, unused by the new path. Removing it is a
  separate decision, and deleting a table is not something to do in the same
  release as adding its replacement.

## What would make us revisit this

- A product needing a genuine per-size cost that is not a multiple of the
  batch (option C).
- Families whose names change often enough that orphans are routine.
- A second outlet with different recipes for the same product name — at
  which point `family_key` needs an outlet dimension.
