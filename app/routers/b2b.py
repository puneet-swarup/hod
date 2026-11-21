"""B2B partner routes — accounts, contracts, price lists, statements.

HTTP only; business logic lives in app.services.b2b_service.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import b2b_service
from app.services.product_service import list_products
from app.utils.time import business_now

router = APIRouter()


def _ctx(request: Request, **extra) -> dict:
    return {
        "settings": request.app.state.settings,
        "today_iso": business_now().date().isoformat(),
        **extra,
    }


async def _form_dict(request: Request) -> dict:
    """request.form() as a plain dict, with multi-value fields flattened.

    The dispatch-day checkboxes post several values; the form re-renders
    from this dict, so joining them keeps the template simple.
    """
    form = await request.form()
    data = {key: form.get(key) for key in form}
    days = form.getlist("dispatch_days")
    if days:
        data["dispatch_days"] = ",".join(days)
    return data


# ============================================================
# List / create
# ============================================================


@router.get("/", response_class=HTMLResponse)
def list_page(request: Request, all: int = 0, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    accounts = b2b_service.list_accounts(db, include_inactive=bool(all))

    cards = []
    for account in accounts:
        credit = b2b_service.credit_position(db, account)
        cards.append({"account": account, "credit": credit})

    return templates.TemplateResponse(
        request=request,
        name="partners/list.html",
        context=_ctx(request, cards=cards, show_inactive=bool(all)),
    )


@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="partners/form.html",
        context=_ctx(request, account=None, form_action="/b2b/", mode="create"),
    )


@router.post("/", response_class=HTMLResponse)
async def create(request: Request, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    form = await _form_dict(request)
    try:
        account = b2b_service.create_account(db, form)
    except HTTPException as exc:
        return templates.TemplateResponse(
            request=request,
            name="partners/form.html",
            context=_ctx(
                request,
                account=None,
                form_action="/b2b/",
                mode="create",
                error=exc.detail,
                form_data=form,
            ),
            status_code=400,
        )
    return RedirectResponse(url=f"/b2b/{account.id}", status_code=303)


@router.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Type-ahead used by the order form's partner field."""
    templates = request.app.state.templates
    if len((q or "").strip()) < 2:
        return HTMLResponse("")
    results = b2b_service.search_accounts(db, q)
    return templates.TemplateResponse(
        request=request,
        name="partners/search_results.html",
        context={"results": results, "q": q.strip()},
    )


# ============================================================
# Detail / edit
# ============================================================


@router.get("/{account_id}", response_class=HTMLResponse)
def detail(request: Request, account_id: int, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    account = b2b_service.get_account(db, account_id)

    contract = b2b_service.active_contract(db, account.id, business_now().date())
    return templates.TemplateResponse(
        request=request,
        name="partners/detail.html",
        context=_ctx(
            request,
            account=account,
            contract=contract,
            terms=b2b_service.effective_terms(account, contract),
            credit=b2b_service.credit_position(db, account),
            orders=b2b_service.account_orders(db, account.id, limit=10),
            products=list_products(db, include_inactive=False),
            margin=b2b_service.margin_by_partner(db, account.id),
        ),
    )


@router.get("/{account_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, account_id: int, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    account = b2b_service.get_account(db, account_id)
    return templates.TemplateResponse(
        request=request,
        name="partners/form.html",
        context=_ctx(
            request,
            account=account,
            form_action=f"/b2b/{account.id}/edit",
            mode="edit",
        ),
    )


@router.post("/{account_id}/edit", response_class=HTMLResponse)
async def edit(request: Request, account_id: int, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    account = b2b_service.get_account(db, account_id)
    form = await _form_dict(request)
    try:
        b2b_service.update_account(db, account_id, form)
    except HTTPException as exc:
        return templates.TemplateResponse(
            request=request,
            name="partners/form.html",
            context=_ctx(
                request,
                account=account,
                form_action=f"/b2b/{account_id}/edit",
                mode="edit",
                error=exc.detail,
                form_data=form,
            ),
            status_code=400,
        )
    return RedirectResponse(url=f"/b2b/{account_id}", status_code=303)


@router.post("/{account_id}/deactivate")
def deactivate(account_id: int, db: Session = Depends(get_db)):
    b2b_service.deactivate_account(db, account_id)
    return RedirectResponse(url="/b2b/?all=1", status_code=303)


# ============================================================
# Contracts and prices
# ============================================================


@router.post("/{account_id}/contracts")
async def add_contract(request: Request, account_id: int, db: Session = Depends(get_db)):
    form = dict(await request.form())
    b2b_service.create_contract(db, account_id, form)
    return RedirectResponse(url=f"/b2b/{account_id}", status_code=303)


@router.post("/{account_id}/prices")
async def add_price(request: Request, account_id: int, db: Session = Depends(get_db)):
    form = dict(await request.form())
    b2b_service.upsert_price_item(db, account_id, form)
    return RedirectResponse(url=f"/b2b/{account_id}", status_code=303)


@router.post("/{account_id}/prices/{item_id}/delete")
def delete_price(account_id: int, item_id: int, db: Session = Depends(get_db)):
    b2b_service.delete_price_item(db, account_id, item_id)
    return RedirectResponse(url=f"/b2b/{account_id}", status_code=303)


# ============================================================
# Live quote (order form preview)
# ============================================================


@router.get("/{account_id}/quote")
def quote(
    account_id: int,
    items: str = Query("", description="product_id:qty pairs, comma separated"),
    fulfillment: str = Query("", description="ISO datetime-local value"),
    db: Session = Depends(get_db),
):
    """Price a basket for this partner without writing anything.

    The order form calls this as the user edits lines, so the prices and
    the commercial warnings are visible before the order is placed.
    """
    account = b2b_service.get_account(db, account_id)

    parsed: list[dict] = []
    for chunk in (items or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            product_id, qty = chunk.split(":")
            parsed.append({"product_id": int(product_id), "quantity": int(qty)})
        except ValueError:
            continue

    if not parsed:
        return JSONResponse({"lines": [], "warnings": [], "total": "0.00"})

    fulfillment_dt = None
    if fulfillment:
        try:
            fulfillment_dt = datetime.fromisoformat(fulfillment)
        except ValueError:
            fulfillment_dt = None

    evaluation = b2b_service.evaluate_order(db, account, parsed, fulfillment_dt)
    return JSONResponse(
        {
            "lines": [
                {
                    "product_id": ln["product_id"],
                    "name": ln["name"],
                    "sku": ln["sku"],
                    "quantity": ln["quantity"],
                    "unit_price": str(ln["unit_price"]),
                    "line_total": str(ln["line_total"]),
                    "source": ln["source"],
                    "price_label": ln["price_label"],
                }
                for ln in evaluation["lines"]
            ],
            "subtotal": str(evaluation["subtotal"]),
            "gst_total": str(evaluation["gst_total"]),
            "total": str(evaluation["total"]),
            "warnings": evaluation["warnings"],
            "credit": {
                "limit": str(evaluation["credit"]["limit"]),
                "outstanding": str(evaluation["credit"]["outstanding"]),
                "projected": str(evaluation["credit"]["projected"]),
                "over_limit": evaluation["credit"]["over_limit"],
            },
        }
    )


# ============================================================
# Statement
# ============================================================


@router.get("/{account_id}/statement", response_class=HTMLResponse)
def statement_page(request: Request, account_id: int, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    account = b2b_service.get_account(db, account_id)
    data = b2b_service.statement(db, account)
    return templates.TemplateResponse(
        request=request,
        name="partners/statement.html",
        context=_ctx(request, account=account, data=data),
    )


@router.get("/{account_id}/statement.csv")
def statement_csv(account_id: int, db: Session = Depends(get_db)):
    account = b2b_service.get_account(db, account_id)
    data = b2b_service.statement(db, account)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Partner", account.name, account.code])
    writer.writerow(["Generated", business_now().strftime("%Y-%m-%d %H:%M")])
    writer.writerow([])
    writer.writerow(["Order", "Date", "Status", "PO ref", "Total", "Paid", "Balance"])
    for row in data["rows"]:
        order = row["order"]
        writer.writerow(
            [
                order.order_number,
                order.order_date.strftime("%Y-%m-%d"),
                order.status.value,
                row["po"] or "",
                f"{row['total']:.2f}",
                f"{row['paid']:.2f}",
                f"{row['balance']:.2f}",
            ]
        )
    writer.writerow([])
    writer.writerow(["Billed", f"{data['billed']:.2f}"])
    writer.writerow(["Received", f"{data['received']:.2f}"])
    writer.writerow(["Outstanding", f"{data['outstanding']:.2f}"])

    filename = f"{account.code}-statement-{business_now():%Y%m%d}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
