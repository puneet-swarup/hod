"""Product CRUD routes + recipe editor."""

from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Product
from app.services import inventory_service, product_service, recipe_service
from app.utils.sku import validate_sku_format

router = APIRouter()


# ---------------------------------------------------------------
# List
# ---------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def list_products_page(request: Request, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    settings = request.app.state.settings
    products = product_service.list_products(db, include_inactive=True)

    # Products sharing a name are sizes of one thing; the header counts both.
    families: dict[str, list] = {}
    for product in products:
        families.setdefault(product.family_key, []).append(product)

    capacities = recipe_service.capacity_for_products(db, [p.id for p in products])

    # Per-product unit cost and margin. Small bakery with a handful of
    # SKUs — the per-product loop is fine. If it ever matters, batch it.
    economics: dict[int, dict] = {}
    for p in products:
        cost = recipe_service.recipe_cost(db, p.id)
        price = p.base_price or Decimal("0.00")
        margin = price - cost
        pct = (margin / price * 100).quantize(Decimal("0.01")) if price > 0 else Decimal("0.00")
        economics[p.id] = {
            "unit_cost": cost,
            "unit_price": price,
            "unit_margin": margin,
            "margin_pct": pct,
            "has_recipe": cost > 0,
        }

    return templates.TemplateResponse(
        request=request,
        name="products/list.html",
        context={
            "settings": settings,
            "products": products,
            "capacities": capacities,
            "economics": economics,
            "families": families,
        },
    )


# ---------------------------------------------------------------
# Type-ahead (order form)
# ---------------------------------------------------------------


@router.get("/search", response_class=HTMLResponse)
def search_products(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Type-ahead for the order form's product field.

    Matches name, SKU or category, active products only, at most 10 rows.
    Declared before the /{product_id}/... routes so it is never captured
    as a product id.
    """
    templates = request.app.state.templates
    q_clean = (q or "").strip()
    if len(q_clean) < 2:
        return HTMLResponse("")

    term = f"%{q_clean}%"
    results = (
        db.execute(
            select(Product)
            .where(
                Product.is_active.is_(True),
                or_(
                    Product.name.ilike(term),
                    Product.sku.ilike(term),
                    Product.category.ilike(term),
                ),
            )
            .order_by(Product.name)
            .limit(10)
        )
        .scalars()
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="products/search_results.html",
        context={"results": results, "q": q_clean},
    )


# ---------------------------------------------------------------
# Size labels — one screen for every family
# ---------------------------------------------------------------


def _suggest_label(product, has_siblings: bool) -> str:
    """A sensible size for a product that has none yet.

    Never invents a measurement: it only turns data the product already
    carries (pack size, pack label, measure) into the wording a customer
    would use. A single piece inside a family becomes "1 pc", which is the
    case that otherwise reads as a bare product name.
    """
    if product.variant_label:
        return product.variant_label
    if product.pack_label:
        return product.pack_label
    if product.measure_value is not None and product.measure_unit:
        return f"{product.measure_value:g} {product.measure_unit}"
    if product.pack_size and product.pack_size > 1:
        return f"{product.pack_size} pc"
    if has_siblings:
        return "1 pc"
    return ""


@router.get("/sizes", response_class=HTMLResponse)
def size_labels_page(request: Request, db: Session = Depends(get_db)):
    """Every product that has siblings, with an editable size label."""
    templates = request.app.state.templates
    products = product_service.list_products(db, include_inactive=False)

    grouped: dict[str, list] = {}
    for product in products:
        grouped.setdefault(product.family_key, []).append(product)

    families = []
    for members in grouped.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda p: (p.base_price or 0))
        families.append(
            {
                "name": members[0].name,
                "categories": sorted({m.category for m in members}),
                "rows": [
                    {
                        "product": m,
                        "suggestion": _suggest_label(m, has_siblings=True),
                    }
                    for m in members
                ],
            }
        )
    families.sort(key=lambda f: f["name"].lower())

    return templates.TemplateResponse(
        request=request,
        name="products/sizes.html",
        context={
            "settings": request.app.state.settings,
            "families": families,
            "missing": sum(1 for f in families for r in f["rows"] if not r["product"].variant_label),
        },
    )


@router.post("/sizes", response_class=HTMLResponse)
async def save_size_labels(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    updated = 0
    for key, value in form.items():
        if not key.startswith("label_"):
            continue
        try:
            product_id = int(key.split("_", 1)[1])
        except ValueError:
            continue
        product = product_service.get_product(db, product_id)
        label = str(value).strip() or None
        if product.variant_label != label:
            product.variant_label = label
            updated += 1
    db.commit()
    return RedirectResponse(url=f"/products/?sizes={updated}", status_code=303)


# ---------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------


def _parse_import_rows(raw: str) -> tuple[list[dict], list[str]]:
    """Parse pasted CSV into product rows. Returns (rows, errors).

    Accepted columns, in order: name, size, price, gst, category.
    A header line is skipped. Blank lines are ignored. Sizes sharing a name
    become variants of one product automatically.
    """
    import csv
    import io

    rows: list[dict] = []
    errors: list[str] = []

    reader = csv.reader(io.StringIO(raw))
    first_content_row = True
    for number, cells in enumerate(reader, start=1):
        cells = [c.strip() for c in cells]
        if not any(cells):
            continue
        if first_content_row:
            first_content_row = False
            if cells[0].lower() in {"name", "product", "item"}:
                continue  # a header line, wherever it sits
        if len(cells) < 3:
            errors.append(f"line {number}: expected at least name, size, price")
            continue

        name, size, price = cells[0], cells[1], cells[2]
        gst = cells[3] if len(cells) > 3 and cells[3] else "5"
        category = cells[4] if len(cells) > 4 and cells[4] else "Cake"

        if not name:
            errors.append(f"line {number}: name is empty")
            continue
        try:
            price_value = float(price)
            if price_value <= 0:
                raise ValueError
        except ValueError:
            errors.append(f"line {number}: price '{price}' is not a positive number")
            continue
        try:
            gst_value = float(gst)
        except ValueError:
            errors.append(f"line {number}: GST '{gst}' is not a number")
            continue

        rows.append(
            {
                "name": name,
                "variant_label": size or None,
                "base_price": price_value,
                "gst_rate": gst_value,
                "category": category,
                "pack_size": 1,
                "pack_label": "",
                "prep_time_hours": 4,
                "is_active": True,
            }
        )
    return rows, errors


@router.get("/import", response_class=HTMLResponse)
def import_products_page(request: Request, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="products/import.html",
        context={"settings": request.app.state.settings, "raw": ""},
    )


@router.post("/import", response_class=HTMLResponse)
async def import_products(request: Request, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    form = await request.form()
    raw = str(form.get("rows") or "")

    rows, errors = _parse_import_rows(raw)
    if not rows and not errors:
        errors.append("Nothing to import — paste some rows first.")

    # All or nothing: a half-imported catalogue is worse than none.
    created = 0
    if not errors:
        try:
            for row in rows:
                product_service.create_product(db, dict(row))
                created += 1
            db.commit()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            db.rollback()
            created = 0
            errors.append(f"Nothing was imported: {exc}")

    if errors:
        return templates.TemplateResponse(
            request=request,
            name="products/import.html",
            context={
                "settings": request.app.state.settings,
                "raw": raw,
                "errors": errors,
                "parsed": len(rows),
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/products/?imported={created}", status_code=303)


# ---------------------------------------------------------------
# Create
# ---------------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
def new_product_form(request: Request):
    templates = request.app.state.templates
    settings = request.app.state.settings
    return templates.TemplateResponse(
        request=request,
        name="products/form.html",
        context={"settings": settings, "product": None},
    )


@router.get("/check-sku")
def check_sku(
    sku: str = "",
    exclude_id: int | None = None,
    db: Session = Depends(get_db),
):
    if not sku.strip():
        return {"available": True, "normalized": "", "reason": None}
    try:
        normalized = validate_sku_format(sku)
    except ValueError:
        return {"available": False, "normalized": "", "reason": "invalid"}
    available = product_service.is_sku_available(db, normalized, exclude_product_id=exclude_id)
    return {
        "available": available,
        "normalized": normalized,
        "reason": None if available else "duplicate",
    }


@router.post("/", response_class=HTMLResponse)
def create_product(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    sku: str = Form(""),
    category: str = Form("Cake"),
    measure_value: str = Form(""),
    measure_unit: str = Form(""),
    pack_size: int = Form(1),
    pack_label: str = Form(""),
    variant_label: str = Form(""),
    base_price: float = Form(...),
    gst_rate: float = Form(5.0),
    prep_time_hours: int = Form(4),
    description: str = Form(None),
    is_active: str = Form("1"),
):
    templates = request.app.state.templates
    settings = request.app.state.settings

    data = {
        "name": name.strip(),
        "sku": sku.strip(),
        "category": category,
        "measure_value": measure_value.strip() or None,
        "measure_unit": measure_unit.strip() or None,
        "pack_size": pack_size,
        "pack_label": pack_label.strip(),
        "variant_label": variant_label.strip() or None,
        "base_price": base_price,
        "gst_rate": gst_rate,
        "prep_time_hours": prep_time_hours,
        "description": description or None,
        "is_active": is_active == "1",
    }

    try:
        product = product_service.create_product(db, data)
    except Exception as e:
        return templates.TemplateResponse(
            request=request,
            name="products/form.html",
            context={"settings": settings, "product": None, "error": str(e), "form_data": data},
            status_code=400,
        )

    return RedirectResponse(url=f"/products/{product.id}/recipe", status_code=303)


# ---------------------------------------------------------------
# Edit / Delete
# ---------------------------------------------------------------


@router.get("/{product_id}/edit", response_class=HTMLResponse)
def edit_product_form(request: Request, product_id: int, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    settings = request.app.state.settings
    product = product_service.get_product(db, product_id)

    # Other sizes of the same thing, so labelling a family is one tap apart.
    siblings = [
        other
        for other in product_service.list_products(db, include_inactive=True)
        if other.id != product.id and other.family_key == product.family_key
    ]
    siblings.sort(key=lambda p: p.base_price or 0)

    return templates.TemplateResponse(
        request=request,
        name="products/form.html",
        context={"settings": settings, "product": product, "siblings": siblings},
    )


@router.post("/{product_id}/edit", response_class=HTMLResponse)
def update_product(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    sku: str = Form(""),
    category: str = Form("Cake"),
    measure_value: str = Form(""),
    measure_unit: str = Form(""),
    pack_size: int = Form(1),
    pack_label: str = Form(""),
    variant_label: str = Form(""),
    base_price: float = Form(...),
    gst_rate: float = Form(5.0),
    prep_time_hours: int = Form(4),
    description: str = Form(None),
    is_active: str = Form("1"),
):
    templates = request.app.state.templates
    settings = request.app.state.settings

    data = {
        "name": name.strip(),
        "sku": sku.strip(),
        "category": category,
        "measure_value": measure_value.strip() or None,
        "measure_unit": measure_unit.strip() or None,
        "pack_size": pack_size,
        "pack_label": pack_label.strip(),
        "variant_label": variant_label.strip() or None,
        "base_price": base_price,
        "gst_rate": gst_rate,
        "prep_time_hours": prep_time_hours,
        "description": description or None,
        "is_active": is_active == "1",
    }

    try:
        product_service.update_product(db, product_id, data)
    except Exception as e:
        product = product_service.get_product(db, product_id)
        return templates.TemplateResponse(
            request=request,
            name="products/form.html",
            context={"settings": settings, "product": product, "error": str(e), "form_data": data},
            status_code=400,
        )

    return RedirectResponse(url="/products", status_code=303)


@router.post("/{product_id}/delete")
def delete_product_route(product_id: int, db: Session = Depends(get_db)):
    product_service.delete_product(db, product_id)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------
# Recipe editor
# ---------------------------------------------------------------


@router.get("/{product_id}/recipe", response_class=HTMLResponse)
def recipe_editor(
    request: Request,
    product_id: int,
    saved: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    templates = request.app.state.templates
    settings = request.app.state.settings

    product = product_service.get_product(db, product_id)
    recipe_lines = recipe_service.list_recipe(db, product_id)
    capacity = recipe_service.capacity_for_product(db, product_id)
    recipe_cost = recipe_service.recipe_cost(db, product_id)
    ingredients = inventory_service.list_ingredients(db, include_inactive=False)

    return templates.TemplateResponse(
        request=request,
        name="products/recipe.html",
        context={
            "settings": settings,
            "product": product,
            "recipe_lines": recipe_lines,
            "capacity": capacity,
            "recipe_cost": recipe_cost,
            "ingredients": ingredients,
            "saved": saved,
            "error": error,
        },
    )


@router.post("/{product_id}/recipe", response_class=HTMLResponse)
async def recipe_save(request: Request, product_id: int, db: Session = Depends(get_db)):
    form = await request.form()
    ing_ids = form.getlist("ingredient_id")
    quantities = form.getlist("quantity")
    unit_rows = form.getlist("unit")

    lines: list[dict] = []
    for idx, (iid_raw, qty_raw) in enumerate(zip(ing_ids, quantities, strict=False)):
        iid = (iid_raw or "").strip()
        qty = (qty_raw or "").strip()
        if not iid or not qty:
            continue
        unit = ""
        if idx < len(unit_rows):
            unit = (unit_rows[idx] or "").strip()
        try:
            lines.append(
                {
                    "ingredient_id": int(iid),
                    "quantity_per_unit": qty,
                    "unit": unit or None,
                }
            )
        except (ValueError, TypeError):
            return RedirectResponse(
                url=f"/products/{product_id}/recipe?error=Invalid+row",
                status_code=303,
            )

    try:
        recipe_service.replace_recipe(db, product_id, lines)
    except Exception as exc:
        from urllib.parse import quote

        return RedirectResponse(
            url=f"/products/{product_id}/recipe?error={quote(str(exc))}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/products/{product_id}/recipe?saved=1",
        status_code=303,
    )
