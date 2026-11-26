"""Costing screens: the cost sheet, the recipe editor and the assumptions.

The router renders and delegates. Every calculation happens in
``costing_service``, which delegates the arithmetic to the pure calculator —
so this file contains no maths at all.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import costing_service, product_service

router = APIRouter()


def _families(db: Session) -> list[dict]:
    """One row per product family, with what it is costing."""
    products = product_service.list_products(db, include_inactive=False)
    grouped: dict[str, list] = {}
    for product in products:
        grouped.setdefault(product.family_key, []).append(product)

    rows = []
    for family_key, members in grouped.items():
        members.sort(key=lambda p: p.base_price or 0)
        recipe = costing_service.recipe_for(db, family_key)
        rows.append(
            {
                "family_key": family_key,
                "name": members[0].name,
                "products": members,
                "recipe": recipe,
                "costed": recipe is not None,
            }
        )
    rows.sort(key=lambda r: (r["costed"], r["name"].lower()))
    return rows


@router.get("/", response_class=HTMLResponse)
def costing_index(request: Request, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    rows = _families(db)
    return templates.TemplateResponse(
        request=request,
        name="costing/index.html",
        context={
            "settings": request.app.state.settings,
            "rows": rows,
            "costed": sum(1 for r in rows if r["costed"]),
            "total": len(rows),
        },
    )


# ---------------------------------------------------------------------------
# Bulk entry — the difference between "a nice module" and "one that gets used"
# ---------------------------------------------------------------------------


def _parse_ingredient_rows(raw: str) -> tuple[list[dict], list[str]]:
    """Parse pasted ingredient lines: name, unit, cost per unit."""
    import csv
    import io

    rows: list[dict] = []
    errors: list[str] = []
    first = True

    for number, cells in enumerate(csv.reader(io.StringIO(raw)), start=1):
        cells = [c.strip() for c in cells]
        if not any(cells):
            continue
        if first:
            first = False
            if cells[0].lower() in {"name", "ingredient"}:
                continue
        if len(cells) < 3:
            errors.append(f"line {number}: expected name, unit, cost")
            continue
        try:
            cost = float(cells[2])
            if cost < 0:
                raise ValueError
        except ValueError:
            errors.append(f"line {number}: cost '{cells[2]}' is not a number")
            continue
        rows.append({"name": cells[0], "unit": cells[1] or "g", "cost": cost})

    return rows, errors


def _parse_recipe_rows(raw: str) -> tuple[dict[str, list[dict]], list[str]]:
    """Parse pasted recipe lines: family, ingredient, quantity[, batch yield]."""
    import csv
    import io

    families: dict[str, list[dict]] = {}
    yields: dict[str, int] = {}
    errors: list[str] = []
    first = True

    for number, cells in enumerate(csv.reader(io.StringIO(raw)), start=1):
        cells = [c.strip() for c in cells]
        if not any(cells):
            continue
        if first:
            first = False
            if cells[0].lower() in {"family", "product"}:
                continue
        if len(cells) < 3:
            errors.append(f"line {number}: expected family, ingredient, quantity")
            continue
        family, ingredient, quantity = cells[0], cells[1], cells[2]
        if not family:
            errors.append(f"line {number}: family is empty")
            continue
        try:
            qty = float(quantity)
            if qty <= 0:
                raise ValueError
        except ValueError:
            errors.append(f"line {number}: quantity '{quantity}' is not positive")
            continue
        if len(cells) > 3 and cells[3]:
            try:
                yields[family] = int(cells[3])
            except ValueError:
                errors.append(f"line {number}: batch yield '{cells[3]}' is not a number")
                continue
        families.setdefault(family, []).append({"name": ingredient, "quantity": qty})

    for family in families:
        yields.setdefault(family, 24)

    return {"families": families, "yields": yields}, errors


@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="costing/import.html",
        context={
            "settings": request.app.state.settings,
            "ingredients": _ingredients(db),
            "recipes": costing_service.list_recipes(db),
        },
    )


@router.post("/import/ingredients", response_class=HTMLResponse)
async def import_ingredients(request: Request, db: Session = Depends(get_db)):
    from app.services import inventory_service

    templates = request.app.state.templates
    form = await request.form()
    raw = str(form.get("rows") or "")

    rows, errors = _parse_ingredient_rows(raw)
    if not rows and not errors:
        errors.append("Nothing to import — paste some rows first.")

    created = 0
    if not errors:
        try:
            for row in rows:
                inventory_service.create_ingredient(
                    db,
                    {
                        "name": row["name"],
                        "unit": row["unit"],
                        "kind": "RAW",
                        "cost_per_unit": row["cost"],
                        "reorder_threshold": 0,
                        "is_active": True,
                    },
                )
                created += 1
            db.commit()
        except Exception as exc:  # noqa: BLE001 - surfaced to the owner
            db.rollback()
            created = 0
            errors.append(f"Nothing was imported: {exc}")

    if errors:
        return templates.TemplateResponse(
            request=request,
            name="costing/import.html",
            context={
                "settings": request.app.state.settings,
                "ingredients": _ingredients(db),
                "recipes": costing_service.list_recipes(db),
                "errors": errors,
                "raw_ingredients": raw,
            },
            status_code=400,
        )
    return RedirectResponse(url=f"/costing/import?ingredients={created}", status_code=303)


@router.post("/import/recipes", response_class=HTMLResponse)
async def import_recipes(request: Request, db: Session = Depends(get_db)):
    from app.services import inventory_service

    templates = request.app.state.templates
    form = await request.form()
    raw = str(form.get("rows") or "")

    parsed, errors = _parse_recipe_rows(raw)
    families = parsed["families"] if parsed else {}
    yields = parsed["yields"] if parsed else {}

    if not families and not errors:
        errors.append("Nothing to import — paste some rows first.")

    # Ingredients are matched by name, because that is what a person pastes.
    by_name = {i.name.strip().lower(): i for i in inventory_service.list_ingredients(db)}

    created = 0
    if not errors:
        try:
            for family, lines in families.items():
                resolved = []
                for line in lines:
                    ingredient = by_name.get(line["name"].strip().lower())
                    if ingredient is None:
                        raise ValueError(f"Unknown ingredient: {line['name']}")
                    resolved.append(
                        {"ingredient_id": ingredient.id, "quantity": line["quantity"]}
                    )
                costing_service.save_recipe(
                    db,
                    family_key=" ".join(family.lower().split()),
                    name=family,
                    yield_pieces=yields.get(family, 24),
                    lines=resolved,
                )
                created += 1
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            created = 0
            errors.append(f"Nothing was imported: {exc}")

    if errors:
        return templates.TemplateResponse(
            request=request,
            name="costing/import.html",
            context={
                "settings": request.app.state.settings,
                "ingredients": _ingredients(db),
                "recipes": costing_service.list_recipes(db),
                "errors": errors,
                "raw_recipes": raw,
            },
            status_code=400,
        )
    return RedirectResponse(url=f"/costing/import?recipes={created}", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="costing/settings.html",
        context={
            "settings": request.app.state.settings,
            "costing": costing_service.get_settings(db),
        },
    )


@router.post("/settings", response_class=HTMLResponse)
async def save_settings(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    costing_service.update_settings(db, dict(form))
    db.commit()
    return RedirectResponse(url="/costing/?settings=1", status_code=303)


@router.get("/{product_id}", response_class=HTMLResponse)
def cost_sheet(request: Request, product_id: int, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    product = product_service.get_product(db, product_id)

    return templates.TemplateResponse(
        request=request,
        name="costing/sheet.html",
        context={
            "settings": request.app.state.settings,
            "sheet": costing_service.cost_sheet(db, product),
            "siblings": [
                p
                for p in product_service.list_products(db, include_inactive=False)
                if p.family_key == product.family_key
            ],
            "ingredients": _ingredients(db),
            "all_products": product_service.list_products(db, include_inactive=False),
        },
    )


def _ingredients(db: Session) -> list:
    from app.services import inventory_service

    return inventory_service.list_ingredients(db)


@router.post("/{product_id}/recipe", response_class=HTMLResponse)
async def save_recipe(request: Request, product_id: int, db: Session = Depends(get_db)):
    form = await request.form()
    product = product_service.get_product(db, product_id)

    ingredient_ids = form.getlist("ingredient_id")
    quantities = form.getlist("quantity")
    lines = [
        {"ingredient_id": iid, "quantity": qty}
        for iid, qty in zip(ingredient_ids, quantities, strict=False)
        if str(iid).strip() and str(qty).strip()
    ]

    costing_service.save_recipe(
        db,
        family_key=product.family_key,
        name=product.name,
        yield_pieces=int(form.get("yield_pieces") or 1),
        labour_minutes=int(form.get("labour_minutes") or 0),
        overhead_per_batch=form.get("overhead_per_batch") or 0,
        wastage_pct=form.get("wastage_pct") or 0,
        notes=form.get("notes") or None,
        lines=lines,
    )
    db.commit()
    return RedirectResponse(url=f"/costing/{product_id}?saved=recipe", status_code=303)


@router.post("/{product_id}/price", response_class=HTMLResponse)
async def apply_price(request: Request, product_id: int, db: Session = Depends(get_db)):
    """Take a suggested price. The only route that changes what a product costs."""
    form = await request.form()
    product = product_service.get_product(db, product_id)
    costing_service.apply_price(db, product, form.get("price") or 0)
    db.commit()
    return RedirectResponse(url=f"/costing/{product_id}?saved=price", status_code=303)


@router.post("/{product_id}/packaging", response_class=HTMLResponse)
async def save_packaging(request: Request, product_id: int, db: Session = Depends(get_db)):
    form = await request.form()
    costing_service.set_packaging(
        db, product_id, str(form.get("name") or ""), form.get("cost") or 0
    )
    db.commit()
    return RedirectResponse(url=f"/costing/{product_id}?saved=packaging", status_code=303)
