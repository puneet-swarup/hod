# Engineering standards

**Status:** in force from 26 November 2026.
**Applies to:** everything in this repository, and every module added to it.
**Why it exists:** this codebase is both a running business system and an
architecture portfolio piece. Those two goals agree more than they
conflict, but only if the standards are written down, measured, and
honestly reported — including where the code currently falls short.

---

## 1. The layering rule

```
router  →  service  →  model
   ↓          ↓
template   utils
```

| Layer | May import | Must never import |
|---|---|---|
| `app/routers/` | services, schemas, templates, FastAPI | — (it is the edge) |
| `app/services/` | models, utils, other services, SQLAlchemy | templates, Jinja, `request` |
| `app/models/` | `database.Base`, `utils` | services, routers, FastAPI |
| `app/utils/` | standard library, `decimal` | anything from `app` except other utils |

One rule carries most of the weight: **a service never renders and a model
never queries.** Everything else follows from it.

### Why the layering is worth enforcing

It is what makes the test suite fast and the behaviour predictable. A
service test needs a database session, not an HTTP client. A model test
needs neither. When a bug is found, the layer it lives in tells you where
the fix belongs before you have read the code.

---

## 2. SOLID, applied honestly

Dogmatic SOLID on a 4,000-line application is over-engineering, and saying
so is part of the standard. Below is where each principle actually bites
here, and where it would be ceremony.

| Principle | Where it earns its keep | Where it would be ceremony |
|---|---|---|
| **S**ingle responsibility | `order_service` (lifecycle) vs `invoice_service` (documents) vs `reports_service` (read models). Keep the seams where they are | Splitting a 40-line service into four classes because each method "does one thing" |
| **O**pen/closed | The B2B channel was added as a layer over orders without touching retail logic — that is the pattern to repeat | A plugin registry for two payment gateways |
| **L**iskov | Every status transition obeys `ALLOWED_TRANSITIONS`; a caller may assume it | Subclassing `Order` per channel |
| **I**nterface segregation | `public_app.py` mounts only public routers — the strongest example in the repo of not forcing a caller to depend on what it does not use | One interface per method |
| **D**ependency inversion | Routers depend on `Depends(get_db)`, services depend on the `Session` abstraction — both testable | A repository interface over SQLAlchemy for every model |

**The test for adding abstraction:** can you name two concrete
implementations today? If not, it is not an abstraction, it is a guess.
The B2B pricing modes (per-unit and commission) are two implementations and
earned their strategy. A `PricingStrategy` interface with one implementation
would not have.

---

## 3. DRY, with a rule for when to extract

Shared already, and to be used rather than re-implemented:

| Concern | Home |
|---|---|
| Money rounding and comparison | `app/utils/money.py` |
| GST per line, line total | `app/utils/money.py` |
| UTC ↔ IST conversion, business day | `app/utils/time.py` |
| Unit normalisation and display | `app/utils/units.py` |
| SKU generation | `app/utils/sku.py` |
| Audit trail | `app/services/audit_service.py` |
| Number series | `app/services/numbering.py` |

**The rule of three:** the second copy of a line is a coincidence, the
third is a function. Money maths is exempt — it is extracted at the *first*
copy, because two implementations of a rounding rule is a bug waiting for a
quarter-end.

**What DRY does not mean here:** templates repeat Tailwind classes, and
that is fine. Duplication of *behaviour* is the problem; duplication of
*markup* is the cost of a design system without a build step.

---

## 4. Testing

### The bar

| Layer | Target | Why |
|---|---|---|
| `utils/` | **100%** | Pure functions, no excuse |
| `services/` | **90%** | Business rules live here |
| `routers/` | **80%** | Covered mostly through integration tests |
| `models/` | via services | Behaviour is exercised through the service that owns it |
| **Overall** | **≥ 85%**, enforced in CI | Current: **83%** |

Coverage is a floor, not a goal. A test that asserts a page returns 200
adds a line to the number and nothing to the confidence.

### What must always have a test

1. **Every money calculation** — GST, line totals, rounding, margin.
   Property-based where the input space is large.
2. **Every status transition**, including the illegal ones.
3. **Every migration**, by running it forward *and* back against a copy of
   real data and asserting the rows survive.
4. **Every bug fixed** — the test is written first, and it fails before the
   fix. The suite is the record of mistakes already paid for.
5. **Every public route** — at least one test that it renders and one that
   it rejects a bad payload.

### Shape

- **Arrange / Act / Assert**, no logic in tests.
- One behaviour per test; the name says the behaviour, not the method.
- Fixtures over setup methods; `conftest.py` holds shared construction.
- No network, no clock dependence, no sleeps. Time is injected or frozen.

---

## 5. Documentation

| Artefact | When | Where |
|---|---|---|
| **ADR** | A decision that is expensive to reverse, or that a future reader would otherwise re-litigate | `docs/adr/NNNN-title.md` |
| **Design doc** | A module before it is built | `docs/design/` |
| **Docstring** | Every service function with a rule in it — say *why*, not *what* | in the code |
| **Runbook** | Anything an operator must do under pressure | `private/DEPLOYMENT.md` |

An ADR is not a changelog. It records: the context, the options considered,
the decision, and **what would make us revisit it**. That last section is
what makes it architecture rather than archaeology.

---

## 6. Definition of done

A change is not finished until every line is true:

- [ ] Layering respected; no service renders, no model queries
- [ ] No new duplication of money, time or unit logic
- [ ] Tests: new behaviour covered, coverage not reduced
- [ ] `ruff check` clean
- [ ] Migration additive; proven forward and back on real data
- [ ] Existing rows unchanged, or the change documented and reversible
- [ ] ADR written if the decision is expensive to reverse
- [ ] Design doc updated if the module's shape changed
- [ ] User manual or training material updated if a screen changed
- [ ] Deployed, or explicitly recorded as not deployed

---

## 7. Known deviations

Recorded rather than hidden. Each is a real departure from the standards
above, with a reason and a trigger for revisiting.

| Deviation | Reality | Why it stands | Revisit when |
|---|---|---|---|
| **Services raise `HTTPException`** | All 8 services import FastAPI; ~97 raise sites | It is idiomatic FastAPI, keeps the code short, and the app is HTTP-only. A domain-exception layer would touch every service for no behavioural gain today | If a service is ever called from a worker, a CLI or a second transport |
| **`app/schemas/product.py` at 0%** | 28 statements untested | The router validates through Pydantic and the service through its own guards, so the schema is currently a thin duplicate | Before it grows behaviour |
| **`escpos_printer.py` at 43%** | 85 statements untested | It talks to hardware; the untested paths are device-specific branches | If a second printer model is supported |
| **`sku.py` at 68%** | 20 statements untested | Collision handling is rare-path | Before the bulk import grows |
| **No repository layer** | Services query SQLAlchemy directly | Two implementations do not exist; a repository would be a guess (§2) | If a second data store appears |

**A deviation is not a licence.** It is a decision with a date and a
trigger, and it belongs in this table so the next reader inherits the
reasoning rather than rediscovering the problem.

---

## 8. How the costing module will meet this

The module proposed in
[`design/costing-and-pricing-module.md`](design/costing-and-pricing-module.md)
is the first test of these standards. Concretely:

| Requirement | How it is met |
|---|---|
| Layering | `costing_service` holds every calculation; `routers/costing.py` renders only; models stay query-free |
| Single responsibility | `CostCalculator` (pure maths, no database) is separate from `CostingService` (loads, saves, audits) |
| Open/closed | Pricing methods (margin / markup / market) are a small strategy, because there are genuinely three |
| DRY | Reuses `utils/money.py`; no second GST implementation |
| Testing | `CostCalculator` is pure and gets **100% coverage with property-based tests**; the service gets integration tests; the screen gets one render test per branch |
| Documentation | ADR 0018 records the family-recipe decision; ADR 0019 records the pricing-method decision |
| Migration | Additive only; proven forward and back against a copy of the live database |
| Reversibility | No existing column is repurposed; the old per-product recipe path keeps working |

**A pure calculator is the point.** If the cost arithmetic is a function of
its arguments and nothing else, it can be tested exhaustively without a
database, a request, or a clock — and it can be shown to a reviewer as the
clearest evidence of how this codebase is built.
