"""
Order business logic.

Key guarantees:
- Single commit per public function.
- Audit entry written in the same transaction.
- Money computed with Decimal, rounded per-line, half-up.
- Status changes validated against ALLOWED_TRANSITIONS.
- Order number from NumberSequence, unique-constrained.
- Edits only allowed while CONFIRMED; total cannot drop below paid.
- Entering IN_PROGRESS deducts ingredients per each item's recipe.
  Stock can go negative; the UI warns but does not block.
- Cancelling from IN_PROGRESS supports salvage (return stock) or waste.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Customer,
    Ingredient,
    MovementReason,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    Product,
    ProductStockMovement,
    StockMovement,
)
from app.services import b2b_service, inventory_service, ready_stock_service, recipe_service
from app.services.audit_service import log_action
from app.services.numbering import next_b2b_order_number, next_order_number
from app.utils.money import gst_for_line, line_total_with_gst, money
from app.utils.time import business_now, utcnow

settings = get_settings()


# ===============================================================
# Reads
# ===============================================================


def list_orders(db: Session, status: str = "ALL") -> list[Order]:
    """Unpaginated list. Sort: fulfillment ASC NULLS LAST, order_date DESC."""
    from sqlalchemy import nullslast

    query = select(Order).order_by(
        nullslast(Order.fulfillment_date.asc()),
        Order.order_date.desc(),
    )
    if status != "ALL":
        try:
            status_enum = OrderStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}") from exc
        query = query.where(Order.status == status_enum)
    return list(db.execute(query).scalars().all())


def search_orders(
    db: Session,
    q: str | None = None,
    status: str = "ALL",
    page: int = 1,
    per_page: int = 25,
) -> tuple[list[Order], dict]:
    """
    Paginated order list with optional status filter and text search.

    Search matches (case-insensitive):
      - Order number, e.g. "0007" matches "HOD-2026-0007"
      - Customer name
      - Customer phone, digits-only
    """
    from sqlalchemy import nullslast, or_

    page = max(1, page)
    per_page = max(1, min(per_page, 100))

    conditions = []
    if status != "ALL":
        try:
            status_enum = OrderStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}") from exc
        conditions.append(Order.status == status_enum)

    if q:
        term = f"%{q.strip()}%"
        phone_digits = "".join(c for c in q if c.isdigit())
        ors = [
            Order.order_number.ilike(term),
            Customer.name.ilike(term),
        ]
        if len(phone_digits) >= 3:
            ors.append(Customer.phone.ilike(f"%{phone_digits}%"))
        conditions.append(or_(*ors))

    base = (
        select(Order)
        .join(Customer, Order.customer_id == Customer.id)
        .order_by(
            nullslast(Order.fulfillment_date.asc()),
            Order.order_date.desc(),
        )
    )
    count_q = select(func.count(Order.id)).join(Customer, Order.customer_id == Customer.id)
    if conditions:
        base = base.where(*conditions)
        count_q = count_q.where(*conditions)

    total = db.execute(count_q).scalar() or 0
    pages = (total + per_page - 1) // per_page if total else 1
    if page > pages:
        page = pages
    offset = (page - 1) * per_page

    rows = list(db.execute(base.limit(per_page).offset(offset)).scalars().all())

    meta = {
        "q": q or "",
        "status": status,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
    }
    return rows, meta


def get_order(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


# ===============================================================
# Writes
# ===============================================================


def create_order(db: Session, data: dict) -> Order:
    """
    data keys:
        customer_id, delivery_type, fulfillment_date, delivery_address, notes,
        items: list of {product_id, quantity, customization_notes},
        advance_paid, advance_method, order_date
    """
    items_data = data.get("items") or []
    if not items_data:
        raise HTTPException(status_code=400, detail="An order must have at least one item")

    account = None
    if data.get("account_id"):
        account = b2b_service.get_account(db, int(data["account_id"]))
        if not account.is_active:
            raise HTTPException(status_code=400, detail="That partner is inactive")
        if not account.customer_id:
            raise HTTPException(
                status_code=400, detail="That partner has no billing customer attached"
            )
    else:
        customer = db.get(Customer, data["customer_id"])
        if not customer or not customer.is_active:
            raise HTTPException(status_code=400, detail="Invalid or inactive customer")

    for attempt in range(2):
        try:
            order = _build_order(db, data, items_data, account)
            db.commit()
            db.refresh(order)
            return order
        except IntegrityError as exc:
            db.rollback()
            if attempt == 1:
                raise HTTPException(
                    status_code=409,
                    detail="Order number conflict, please retry",
                ) from exc

    raise HTTPException(status_code=500, detail="Unreachable")


def update_order(db: Session, order_id: int, data: dict) -> Order:
    """
    Edit an existing order. Only allowed while status == CONFIRMED.
    - Payments already recorded are never touched.
    - Cannot reduce the order total below what has already been paid.
    - Every change is written to the audit log with old/new values.
    - If an invoice has been issued, it is NOT updated.
    """
    order = get_order(db, order_id)

    if order.status != OrderStatus.CONFIRMED:
        raise HTTPException(
            status_code=400,
            detail=f"Order cannot be edited in status {order.status.value}. "
            "Only CONFIRMED orders are editable.",
        )

    items_data = data.get("items") or []
    if not items_data:
        raise HTTPException(status_code=400, detail="An order must have at least one item")

    fulfillment_date = _parse_dt(data.get("fulfillment_date"))
    if not fulfillment_date:
        raise HTTPException(status_code=400, detail="Fulfillment date is required")

    old_snapshot = {
        "fulfillment_date": order.fulfillment_date.isoformat() if order.fulfillment_date else None,
        "delivery_type": order.delivery_type,
        "delivery_address": order.delivery_address,
        "notes": order.notes,
        "total_amount": str(order.total_amount),
        "balance_due": str(order.balance_due),
        "items": [
            {"product_id": it.product_id, "quantity": it.quantity, "line_total": str(it.line_total)}
            for it in order.items
        ],
    }

    # A B2B order is re-priced from its contract on every edit, using the
    # same evaluation the form quotes.
    account = order.account if order.is_b2b else None
    evaluation = (
        b2b_service.evaluate_order(db, account, items_data, fulfillment_date)
        if account is not None
        else None
    )
    priced_lines = evaluation["lines"] if evaluation is not None else None

    new_line_totals: list[dict] = []
    new_total = Decimal("0.00")
    for idx, item_data in enumerate(items_data):
        product = db.get(Product, item_data["product_id"])
        if not product or not product.is_active:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid or inactive product: {item_data['product_id']}",
            )
        qty = int(item_data["quantity"])
        if qty <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be positive")

        if priced_lines is not None:
            list_price = money(priced_lines[idx]["unit_price"])
            unit_price = _charged_price(item_data, list_price)
            gst_rate = priced_lines[idx]["gst_rate"]
        else:
            list_price = money(product.base_price)
            unit_price = _charged_price(item_data, list_price)
            gst_rate = money(product.gst_rate)
        gst_amount = gst_for_line(unit_price, qty, gst_rate)
        line_total = line_total_with_gst(unit_price, qty, gst_amount)

        new_total += line_total
        new_line_totals.append(
            {
                "product_id": product.id,
                "quantity": qty,
                "unit_price": unit_price,
                "list_price": list_price,
                "gst_rate": gst_rate,
                "gst_amount": gst_amount,
                "line_total": line_total,
                "customization_notes": item_data.get("customization_notes") or None,
            }
        )

    new_total = money(new_total)

    if new_total < order.advance_paid:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot reduce total below the amount already paid "
                f"({order.advance_paid}). Process a refund separately."
            ),
        )

    for old_item in list(order.items):
        db.delete(old_item)
    db.flush()

    for row in new_line_totals:
        db.add(OrderItem(order_id=order.id, **row))

    order.fulfillment_date = fulfillment_date
    order.delivery_type = data.get("delivery_type", order.delivery_type)
    order.delivery_address = data.get("delivery_address") or None
    order.notes = data.get("notes") or None

    order.total_amount = new_total
    order.balance_due = money(new_total - order.advance_paid)

    if account is not None and evaluation is not None and order.b2b_terms is not None:
        import json as _json

        order.b2b_terms.warnings_json = _json.dumps(evaluation["warnings"])
        order.b2b_terms.price_snapshot = _json.dumps(
            [
                {
                    "product_id": ln["product_id"],
                    "sku": ln["sku"],
                    "quantity": ln["quantity"],
                    "unit_price": str(ln["unit_price"]),
                    "gst_rate": str(ln["gst_rate"]),
                    "source": ln["source"],
                }
                for ln in evaluation["lines"]
            ]
        )
        if data.get("po_reference") is not None:
            order.b2b_terms.po_reference = (data.get("po_reference") or "").strip() or None
        dispatch = _parse_date(data.get("dispatch_date"))
        if dispatch is not None:
            order.b2b_terms.dispatch_date = dispatch

    log_action(
        db,
        entity_type="Order",
        entity_id=order.id,
        action="UPDATE",
        old_value=old_snapshot,
        new_value={
            "fulfillment_date": order.fulfillment_date.isoformat()
            if order.fulfillment_date
            else None,
            "delivery_type": order.delivery_type,
            "delivery_address": order.delivery_address,
            "notes": order.notes,
            "total_amount": str(order.total_amount),
            "balance_due": str(order.balance_due),
            "items": [
                {
                    "product_id": r["product_id"],
                    "quantity": r["quantity"],
                    "line_total": str(r["line_total"]),
                }
                for r in new_line_totals
            ],
        },
    )
    db.commit()
    db.refresh(order)
    return order


def update_status(
    db: Session,
    order_id: int,
    new_status: str,
    salvage: bool = False,
) -> Order:
    """
    Move the order to a new status. Enforces ALLOWED_TRANSITIONS.

    Side effects:
      CONFIRMED → IN_PROGRESS: deduct ingredients per recipe (consumption).
      IN_PROGRESS → CANCELLED with salvage=True: create matching RETURN
        movements, so consumed ingredients go back to stock.
      IN_PROGRESS → CANCELLED with salvage=False: consumption stands;
        COGS reflects the loss.

    `salvage` is only meaningful for IN_PROGRESS → CANCELLED; ignored otherwise.
    """
    order = get_order(db, order_id)
    try:
        target = OrderStatus(new_status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status}") from exc

    if target == order.status:
        return order

    if not order.can_transition_to(target):
        raise HTTPException(
            status_code=400,
            detail=f"Illegal transition: {order.status.value} -> {target.value}",
        )

    old_status = order.status.value

    if target == OrderStatus.IN_PROGRESS and order.status == OrderStatus.CONFIRMED:
        # Take from the shelf first; only the shortfall is baked to order.
        drawn = ready_stock_service.draw_for_order(db, order)
        _deduct_for_production(db, order, drawn)
    elif target == OrderStatus.CANCELLED and order.status == OrderStatus.IN_PROGRESS and salvage:
        # Put back both halves: the units from stock, and the ingredients
        # that were consumed for the made-to-order part.
        drawn = ready_stock_service.return_for_order(db, order)
        _return_production(db, order, drawn)

    order.status = target

    # A cancelled order cannot be owed money. Keep advance_paid — it is the
    # record of cash taken — but clear the balance, or the order sits in the
    # UI claiming a customer owes ₹1,250 on something that was cancelled.
    if target == OrderStatus.CANCELLED:
        order.balance_due = Decimal("0.00")

    log_action(
        db,
        entity_type="Order",
        entity_id=order.id,
        action="STATUS_CHANGE",
        old_value={"status": old_status},
        new_value={
            "status": target.value,
            "salvage": salvage if target == OrderStatus.CANCELLED else None,
            "balance_cleared": str(order.balance_due) if target == OrderStatus.CANCELLED else None,
        },
    )
    db.commit()
    db.refresh(order)
    return order


def record_payment(
    db: Session,
    order_id: int,
    amount: Decimal | float,
    method: str,
    reference: str | None,
    received_at: datetime | None = None,
) -> Order:
    """Record a payment. Updates balance only — never touches status."""
    order = get_order(db, order_id)

    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Cannot record payment on a cancelled order")

    amt = money(amount)
    if amt <= 0:
        raise HTTPException(status_code=400, detail="Payment amount must be positive")
    if amt > order.balance_due:
        raise HTTPException(
            status_code=400,
            detail=f"Payment exceeds balance due ({order.balance_due})",
        )

    payment = Payment(
        order_id=order.id,
        amount=amt,
        method=method,
        reference=reference or None,
        received_at=received_at or utcnow(),
    )
    db.add(payment)
    db.flush()

    order.advance_paid = money(order.advance_paid + amt)
    order.balance_due = money(order.total_amount - order.advance_paid)
    if order.balance_due < 0:
        order.balance_due = Decimal("0.00")

    log_action(
        db,
        entity_type="Payment",
        entity_id=payment.id,
        action="PAYMENT",
        new_value={
            "order_id": order_id,
            "amount": amt,
            "method": method,
            "reference": reference,
            "balance_after": order.balance_due,
        },
    )
    db.commit()
    db.refresh(order)
    return order


# ===============================================================
# Production — deduction, return, COGS, shortages
# ===============================================================


def _compute_needed_ingredients(
    db: Session, order: Order, drawn: dict[int, int] | None = None
) -> dict[int, Decimal]:
    """Sum total consumption per ingredient across all items.

    `drawn` maps product_id -> units taken from ready stock. Those units
    were consumed when they were baked, so they must not be consumed again
    here — that is the double-count that makes a make-to-stock bakery's
    ingredient ledger wrong.
    """
    drawn = drawn or {}
    needed: dict[int, Decimal] = {}
    for item in order.items:
        make_qty = item.quantity - drawn.get(item.product_id, 0)
        if make_qty <= 0:
            continue
        recipe = recipe_service.list_recipe(db, item.product_id)
        for line in recipe:
            qty = line.quantity_per_unit * Decimal(make_qty)
            needed[line.ingredient_id] = needed.get(line.ingredient_id, Decimal("0")) + qty
    return needed


def check_production_shortages(db: Session, order_id: int) -> list[dict]:
    """
    Return ingredients that would go negative if production started now.
    Used for a UI warning banner; does not block.
    """
    order = get_order(db, order_id)
    needed = _compute_needed_ingredients(db, order)
    if not needed:
        return []

    stocks = inventory_service.stocks_for(db, list(needed.keys()))
    shortages = []
    for ing_id, qty in needed.items():
        on_hand = stocks.get(ing_id, Decimal("0"))
        if on_hand < qty:
            ing = db.get(Ingredient, ing_id)
            shortages.append(
                {
                    "ingredient": ing,
                    "needed": qty,
                    "on_hand": on_hand,
                    "shortfall": qty - on_hand,
                }
            )
    return shortages


def _deduct_for_production(
    db: Session, order: Order, drawn: dict[int, int] | None = None
) -> None:
    """
    Create CONSUMPTION movements for the ingredients this order still needs.
    Units taken from ready stock are excluded — they were consumed at bake
    time. Movements are added to the session but NOT committed.
    """
    needed = _compute_needed_ingredients(db, order, drawn)
    for ing_id, qty in needed.items():
        if qty <= 0:
            continue
        inventory_service.record_movement(
            db,
            ing_id,
            delta=-qty,
            reason=MovementReason.CONSUMPTION,
            reference_type="Order",
            reference_id=order.id,
            notes=f"Consumed by {order.order_number}",
            commit=False,
        )


def _return_production(
    db: Session, order: Order, drawn: dict[int, int] | None = None
) -> None:
    """
    Reverse every CONSUMPTION movement tied to this order with a matching
    RETURN. Uses the same unit_cost_at_time, so order_cogs nets to zero.
    """
    consumptions = (
        db.execute(
            select(StockMovement).where(
                StockMovement.reference_type == "Order",
                StockMovement.reference_id == order.id,
                StockMovement.reason == MovementReason.CONSUMPTION,
            )
        )
        .scalars()
        .all()
    )

    for c in consumptions:
        inventory_service.record_movement(
            db,
            c.ingredient_id,
            delta=abs(c.delta),
            reason=MovementReason.RETURN,
            unit_cost=c.unit_cost_at_time,
            reference_type="Order",
            reference_id=order.id,
            notes=f"Salvaged from cancelled {order.order_number}",
            commit=False,
        )


def order_cogs(db: Session, order_id: int) -> Decimal:
    """
    Cost of goods for one order = CONSUMPTION total minus RETURN total
    for movements referencing this order. Salvaged cancels net to zero.
    """

    def _sum(reason: MovementReason) -> Decimal:
        total = db.execute(
            select(func.coalesce(func.sum(StockMovement.total_cost_at_time), 0)).where(
                StockMovement.reference_type == "Order",
                StockMovement.reference_id == order_id,
                StockMovement.reason == reason,
            )
        ).scalar()
        return Decimal(str(total or 0))

    net = _sum(MovementReason.CONSUMPTION) - _sum(MovementReason.RETURN)

    # Units that came off the ready-stock shelf carry their cost with them:
    # the ingredients were consumed when they were baked, so without this
    # an order sold from stock would show a cost of zero.
    from_stock = db.execute(
        select(func.coalesce(func.sum(ProductStockMovement.unit_cost * ProductStockMovement.delta), 0)).where(
            ProductStockMovement.reference_type == "Order",
            ProductStockMovement.reference_id == order_id,
        )
    ).scalar()

    return (net - Decimal(str(from_stock or 0))).quantize(Decimal("0.01"))


# ===============================================================
# Helpers
# ===============================================================


def _build_order(db: Session, data: dict, items_data: list[dict], account=None) -> Order:
    fulfillment_date = _parse_dt(data.get("fulfillment_date"))
    if not fulfillment_date:
        raise HTTPException(
            status_code=400,
            detail="Fulfillment date is required",
        )

    # B2B orders are priced once, by the same evaluation the form quoted, so
    # the stored order and the preview can never disagree.
    evaluation = None
    if account is not None:
        evaluation = b2b_service.evaluate_order(db, account, items_data, fulfillment_date)
        order_number = next_b2b_order_number(db)
        customer_id = account.customer_id
    else:
        order_number = next_order_number(db)
        customer_id = data["customer_id"]

    order = Order(
        order_number=order_number,
        customer_id=customer_id,
        channel="B2B" if account is not None else "RETAIL",
        account_id=account.id if account is not None else None,
        status=OrderStatus.CONFIRMED,
        # order_date is the business calendar date the order was placed,
        # stored as a naive LOCAL datetime (ADR-0017). Default to local now,
        # never utcnow(), or the date flips for orders placed after 18:30 IST.
        order_date=_parse_dt(data.get("order_date")) or business_now().replace(tzinfo=None),
        delivery_type=data.get("delivery_type", "PICKUP"),
        fulfillment_date=fulfillment_date,
        delivery_address=data.get("delivery_address") or None,
        notes=data.get("notes") or None,
    )
    db.add(order)
    db.flush()

    total = Decimal("0.00")

    if evaluation is not None:
        for idx, line in enumerate(evaluation["lines"]):
            db.add(
                OrderItem(
                    order_id=order.id,
                    product_id=line["product_id"],
                    quantity=line["quantity"],
                    unit_price=line["unit_price"],
                    list_price=line["unit_price"],
                    gst_rate=line["gst_rate"],
                    gst_amount=line["gst_amount"],
                    line_total=line["line_total"],
                    customization_notes=(items_data[idx].get("customization_notes") or None),
                )
            )
        total = evaluation["total"]
    else:
        for item_data in items_data:
            product = db.get(Product, item_data["product_id"])
            if not product or not product.is_active:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid or inactive product: {item_data['product_id']}",
                )
            qty = int(item_data["quantity"])
            if qty <= 0:
                raise HTTPException(status_code=400, detail="Quantity must be positive")

            # list_price is what the product is configured at. unit_price is
            # what was charged, which may differ (festival price, discount,
            # negotiated one-off). Both are kept so the difference is visible.
            list_price = money(product.base_price)
            unit_price = _charged_price(item_data, list_price)
            gst_rate = money(product.gst_rate)
            gst_amount = gst_for_line(unit_price, qty, gst_rate)
            line_total = line_total_with_gst(unit_price, qty, gst_amount)

            total += line_total

            db.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=qty,
                    unit_price=unit_price,
                    list_price=list_price,
                    gst_rate=gst_rate,
                    gst_amount=gst_amount,
                    line_total=line_total,
                    customization_notes=item_data.get("customization_notes") or None,
                )
            )

    advance = money(data.get("advance_paid") or 0)
    if advance < 0:
        raise HTTPException(status_code=400, detail="Advance cannot be negative")
    if advance > total:
        raise HTTPException(status_code=400, detail="Advance cannot exceed order total")

    order.total_amount = money(total)
    order.advance_paid = advance
    order.balance_due = money(total - advance)

    if advance > 0:
        db.add(
            Payment(
                order_id=order.id,
                amount=advance,
                method=data.get("advance_method", "UPI"),
            )
        )

    if account is not None and evaluation is not None:
        b2b_service.attach_order_terms(
            db,
            order,
            account,
            evaluation,
            po_reference=data.get("po_reference"),
            dispatch_date=_parse_date(data.get("dispatch_date")),
            payment_terms=data.get("payment_terms") or "CREDIT",
        )

    log_action(
        db,
        entity_type="Order",
        entity_id=order.id,
        action="CREATE",
        new_value={
            "order_number": order.order_number,
            "customer_id": order.customer_id,
            "total_amount": order.total_amount,
            "advance_paid": order.advance_paid,
            "balance_due": order.balance_due,
            "items_count": len(items_data),
        },
    )
    return order


def _charged_price(item_data: dict, list_price: Decimal) -> Decimal:
    """The price actually charged, honouring an explicit override.

    The form may send `unit_price`; when it does not, or sends the same
    number, this is just the list price. An override is never silently
    ignored — a non-positive price is rejected rather than stored.
    """
    raw = item_data.get("unit_price")
    if raw in (None, ""):
        return list_price
    try:
        charged = money(Decimal(str(raw)))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Invalid price on an item") from None
    if charged <= 0:
        raise HTTPException(status_code=400, detail="Price must be greater than zero")
    return charged


def _parse_date(value):
    """ISO date string -> date. None/blank -> None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_dt(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
