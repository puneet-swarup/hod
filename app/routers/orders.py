"""
Order routes. HTTP only; business logic in order_service.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.domain import DomainError
from app.models import B2bAccount, Customer, OrderStatus, Product
from app.services import b2b_service, invoice_service, order_service
from app.utils.time import business_now

router = APIRouter()


def _default_fulfillment() -> str:
    tomorrow_noon = (business_now() + timedelta(days=1)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    return tomorrow_noon.strftime("%Y-%m-%dT%H:%M")


def _product_and_customer_choices(db: Session):
    customers = db.query(Customer).where(Customer.is_active.is_(True)).order_by(Customer.name).all()
    products = db.query(Product).where(Product.is_active.is_(True)).order_by(Product.name).all()
    return customers, products


def _render_order_form_error(
    request: Request,
    db: Session,
    message: str,
    status_code: int = 400,
    data: dict | None = None,
):
    """Re-render the create form with an error banner, keeping what was typed."""
    templates = request.app.state.templates
    settings = request.app.state.settings
    customers, products = _product_and_customer_choices(db)
    return templates.TemplateResponse(
        request=request,
        name="orders/form.html",
        context={
            "settings": settings,
            "customers": customers,
            "products": products,
            "today_date": business_now().strftime("%Y-%m-%d"),
            "default_fulfillment": _default_fulfillment(),
            "mode": "create",
            "form_action": "/orders/",
            "error": message,
            "form_data": data or {},
        },
        status_code=status_code,
    )


@router.get("/", response_class=HTMLResponse)
def list_orders_page(
    request: Request,
    status: str = "ALL",
    q: str = "",
    page: int = 1,
    db: Session = Depends(get_db),
):
    templates = request.app.state.templates
    settings = request.app.state.settings

    try:
        orders, meta = order_service.search_orders(db, q=q or None, status=status, page=page)
    except Exception:
        db.rollback()
        orders, meta = (
            [],
            {
                "q": q,
                "status": status,
                "page": 1,
                "per_page": 25,
                "total": 0,
                "pages": 1,
                "has_prev": False,
                "has_next": False,
            },
        )

    # Attach a message bundle per order (transient — not persisted).
    from app.services.whatsapp_service import messages_for_order

    for order in orders:
        order.wa_messages = messages_for_order(order)

    return templates.TemplateResponse(
        request=request,
        name="orders/list.html",
        context={
            "settings": settings,
            "orders": orders,
            "filter": status,
            "meta": meta,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_order_form(
    request: Request,
    from_order_id: int | None = None,
    account_id: int | None = None,
    db: Session = Depends(get_db),
):
    """
    New order form. If `from_order_id` is provided, pre-fills the customer
    and item lines from that order — the "repeat order" flow.
    """
    templates = request.app.state.templates
    settings = request.app.state.settings
    customers, products = _product_and_customer_choices(db)

    preset_customer_id: int | None = None
    preset_items: list[dict] = []
    source_order_number: str | None = None
    preset_account: B2bAccount | None = None

    if account_id is not None:
        preset_account = b2b_service.get_account(db, account_id)
        preset_customer_id = preset_account.customer_id

    if from_order_id is not None:
        try:
            src = order_service.get_order(db, from_order_id)
        except DomainError:
            # A stale link is not an error — fall back to a blank form.
            src = None
        if src and src.status != OrderStatus.CANCELLED:
            preset_customer_id = src.customer_id
            source_order_number = src.order_number
            for it in src.items:
                preset_items.append(
                    {
                        "product_id": it.product_id,
                        "quantity": it.quantity,
                        "customization_notes": it.customization_notes or "",
                    }
                )

    return templates.TemplateResponse(
        request=request,
        name="orders/form.html",
        context={
            "settings": settings,
            "customers": customers,
            "products": products,
            "today_date": business_now().strftime("%Y-%m-%d"),
            "default_fulfillment": _default_fulfillment(),
            "mode": "create",
            "form_action": "/orders/",
            "preset_customer_id": preset_customer_id,
            "preset_items": preset_items,
            "source_order_number": source_order_number,
            "preset_account": preset_account,
        },
    )


@router.post("/", response_class=HTMLResponse)
def create_order(
    request: Request,
    db: Session = Depends(get_db),
    customer_id: str = Form("0"),
    channel: str = Form("RETAIL"),
    account_id: str = Form(""),
    po_reference: str = Form(None),
    payment_terms: str = Form("CREDIT"),
    dispatch_date: str = Form(None),
    delivery_type: str = Form("PICKUP"),
    fulfillment_date: str = Form(None),
    delivery_address: str = Form(None),
    notes: str = Form(None),
    advance_paid: float = Form(0),
    advance_method: str = Form("UPI"),
    product_id: list[int] = Form(...),
    quantity: list[int] = Form(...),
    unit_price: list[str] = Form(default=[]),
    order_date: str = Form(None),
):
    templates = request.app.state.templates
    settings = request.app.state.settings

    # The form sends a rate per row, prefilled from the product's configured
    # price. A different number means it was sold above or below list, which
    # the service records rather than silently replacing.
    prices = list(unit_price) + [""] * (len(product_id) - len(unit_price))
    items = [
        {"product_id": pid, "quantity": qty, "unit_price": price}
        for pid, qty, price in zip(product_id, quantity, prices, strict=True)
    ]

    account_pk = int(account_id) if (account_id or "").strip().isdigit() else None
    if (channel or "RETAIL").upper() == "B2B" and account_pk is None:
        return _render_order_form_error(
            request, db, "Pick a B2B partner, or switch back to Retail.", 400
        )

    data = {
        "customer_id": int(customer_id or 0),
        "channel": (channel or "RETAIL").upper(),
        "account_id": account_pk,
        "po_reference": po_reference,
        "payment_terms": payment_terms,
        "dispatch_date": dispatch_date,
        "order_date": order_date,
        "delivery_type": delivery_type,
        "fulfillment_date": fulfillment_date or None,
        "delivery_address": delivery_address or None,
        "notes": notes or None,
        "items": items,
        "advance_paid": advance_paid,
        "advance_method": advance_method,
    }

    try:
        order = order_service.create_order(db, data)
    except Exception as exc:
        db.rollback()
        customers, products = _product_and_customer_choices(db)
        return templates.TemplateResponse(
            request=request,
            name="orders/form.html",
            context={
                "settings": settings,
                "customers": customers,
                "products": products,
                "today_date": business_now().strftime("%Y-%m-%d"),
                "default_fulfillment": _default_fulfillment(),
                "mode": "create",
                "form_action": "/orders/",
                "error": str(exc),
                "form_data": data,
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/orders/{order.id}", status_code=303)


@router.get("/{order_id}/edit", response_class=HTMLResponse)
def edit_order_form(request: Request, order_id: int, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    settings = request.app.state.settings

    order = order_service.get_order(db, order_id)

    if order.status != OrderStatus.CONFIRMED:
        return RedirectResponse(url=f"/orders/{order_id}", status_code=303)

    customers, products = _product_and_customer_choices(db)
    has_invoice = invoice_service.get_invoice_for_order(db, order_id) is not None

    return templates.TemplateResponse(
        request=request,
        name="orders/form.html",
        context={
            "settings": settings,
            "customers": customers,
            "products": products,
            "today_date": business_now().strftime("%Y-%m-%d"),
            "default_fulfillment": _default_fulfillment(),
            "mode": "edit",
            "form_action": f"/orders/{order_id}/edit",
            "order": order,
            "has_invoice": has_invoice,
        },
    )


@router.post("/{order_id}/edit", response_class=HTMLResponse)
def update_order(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    po_reference: str = Form(None),
    payment_terms: str = Form("CREDIT"),
    dispatch_date: str = Form(None),
    delivery_type: str = Form("PICKUP"),
    fulfillment_date: str = Form(None),
    delivery_address: str = Form(None),
    notes: str = Form(None),
    product_id: list[int] = Form(...),
    quantity: list[int] = Form(...),
    unit_price: list[str] = Form(default=[]),
):
    templates = request.app.state.templates
    settings = request.app.state.settings

    # The form sends a rate per row, prefilled from the product's configured
    # price. A different number means it was sold above or below list, which
    # the service records rather than silently replacing.
    prices = list(unit_price) + [""] * (len(product_id) - len(unit_price))
    items = [
        {"product_id": pid, "quantity": qty, "unit_price": price}
        for pid, qty, price in zip(product_id, quantity, prices, strict=True)
    ]

    data = {
        "po_reference": po_reference,
        "payment_terms": payment_terms,
        "dispatch_date": dispatch_date,
        "delivery_type": delivery_type,
        "fulfillment_date": fulfillment_date or None,
        "delivery_address": delivery_address or None,
        "notes": notes or None,
        "items": items,
    }

    try:
        order = order_service.update_order(db, order_id, data)
    except Exception as exc:
        db.rollback()
        # Re-render the edit form with the error
        order = order_service.get_order(db, order_id)
        customers, products = _product_and_customer_choices(db)
        has_invoice = invoice_service.get_invoice_for_order(db, order_id) is not None
        return templates.TemplateResponse(
            request=request,
            name="orders/form.html",
            context={
                "settings": settings,
                "customers": customers,
                "products": products,
                "today_date": business_now().strftime("%Y-%m-%d"),
                "default_fulfillment": _default_fulfillment(),
                "mode": "edit",
                "form_action": f"/orders/{order_id}/edit",
                "order": order,
                "has_invoice": has_invoice,
                "error": str(exc),
                "form_data": data,
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/orders/{order.id}", status_code=303)


@router.get("/{order_id}", response_class=HTMLResponse)
def order_detail(request: Request, order_id: int, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    settings = request.app.state.settings
    order = order_service.get_order(db, order_id)

    from app.services.whatsapp_service import messages_for_order

    whatsapp_messages = messages_for_order(order)

    # Only compute shortages when the next move could be IN_PROGRESS
    shortages = []
    if order.status.value == "CONFIRMED":
        shortages = order_service.check_production_shortages(db, order_id)

    # COGS is zero for orders that never reached IN_PROGRESS.
    cogs = order_service.order_cogs(db, order_id)

    return templates.TemplateResponse(
        request=request,
        name="orders/detail.html",
        context={
            "settings": settings,
            "order": order,
            "whatsapp_messages": whatsapp_messages,
            "shortages": shortages,
            "cogs": cogs,
        },
    )


@router.post("/{order_id}/status")
def update_status(
    order_id: int,
    status: str = Form(...),
    salvage: str = Form("false"),
    db: Session = Depends(get_db),
):
    salvage_bool = salvage.strip().lower() in ("true", "1", "yes", "on")
    order = order_service.update_status(db, order_id, status, salvage=salvage_bool)
    return {"ok": True, "status": order.status.value}


@router.post("/{order_id}/payments")
def add_payment(
    order_id: int,
    db: Session = Depends(get_db),
    amount: float = Form(...),
    method: str = Form("UPI"),
    reference: str = Form(None),
):
    order_service.record_payment(db, order_id, amount, method, reference)
    return RedirectResponse(url=f"/orders/{order_id}", status_code=303)
