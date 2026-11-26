"""B2B channel business logic — partners, contracts, prices, credit.

Rules that matter (see ADR-0016):

- Retail price is never touched. Wholesale lives only in price lists.
- A price is resolved from the contract that covers the order date, so an
  order can always be explained: contract -> slab -> price, or retail.
- Commercial checks (minimum order, cut-off, lead time, dispatch day,
  credit limit) produce WARNINGS, never blocks. A human decides.
- Everything is additive: an account owns one Customer row so that
  ``orders.customer_id`` stays NOT NULL and invoicing/WhatsApp keep working.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.domain import ConflictError, NotFoundError, ValidationError
from app.models import (
    AccountKind,
    B2bAccount,
    B2bContract,
    B2bOrderTerms,
    B2bPriceItem,
    Customer,
    Order,
    OrderStatus,
    PaymentTerms,
    PricingMode,
)
from app.services.audit_service import log_action
from app.utils.money import gst_for_line, line_total_with_gst, money
from app.utils.time import business_now

settings = get_settings()

CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,19}$")
CUTOFF_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

OPEN_STATUSES = (OrderStatus.INQUIRY, OrderStatus.CONFIRMED, OrderStatus.IN_PROGRESS, OrderStatus.READY)

_DOW = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


# ===============================================================
# Accounts
# ===============================================================


def get_account(db: Session, account_id: int) -> B2bAccount:
    account = db.get(B2bAccount, account_id)
    if not account:
        raise NotFoundError(entity="Partner")
    return account


def list_accounts(db: Session, include_inactive: bool = False) -> list[B2bAccount]:
    query = select(B2bAccount).order_by(B2bAccount.name)
    if not include_inactive:
        query = query.where(B2bAccount.is_active.is_(True))
    return list(db.execute(query).scalars().all())


def search_accounts(db: Session, q: str, limit: int = 10) -> list[B2bAccount]:
    term = f"%{(q or '').strip()}%"
    return list(
        db.execute(
            select(B2bAccount)
            .where(
                B2bAccount.is_active.is_(True),
                or_(B2bAccount.name.ilike(term), B2bAccount.code.ilike(term)),
            )
            .order_by(B2bAccount.name)
            .limit(limit)
        )
        .scalars()
        .all()
    )


def _clean_account_data(data: dict) -> dict:
    out = dict(data)
    out["code"] = (out.get("code") or "").strip().upper()
    out["name"] = (out.get("name") or "").strip()
    if not CODE_RE.match(out["code"]):
        raise ValidationError("Partner code must be 3-20 characters: A-Z, 0-9 and dashes.")
    if not out["name"]:
        raise ValidationError("Partner name is required")
    if not (out.get("phone") or "").strip():
        raise ValidationError("A contact phone is required")

    cutoff = (out.get("order_cutoff") or "18:00").strip()
    if not CUTOFF_RE.match(cutoff):
        raise ValidationError("Order cut-off must be HH:MM (24-hour)")
    out["order_cutoff"] = cutoff

    days = out.get("dispatch_days") or ""
    if isinstance(days, (list, tuple)):
        days = ",".join(str(d) for d in days)
    days = ",".join(sorted({d.strip() for d in str(days).split(",") if d.strip()}))
    out["dispatch_days"] = days or "1,2,3,4,5,6"

    for key, cast in (
        ("min_order_value", Decimal),
        ("credit_limit", Decimal),
        ("lead_time_hours", int),
        ("credit_days", int),
    ):
        value = out.get(key)
        if value in (None, ""):
            out[key] = 0 if cast is int else Decimal("0.00")
        else:
            try:
                out[key] = cast(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"Invalid {key}") from exc

    if out.get("kind"):
        try:
            out["kind"] = AccountKind(out["kind"])
        except ValueError as exc:
            raise ValidationError("Invalid partner kind") from exc

    mode = (out.get("production_mode") or "SHARED").upper()
    out["production_mode"] = "DEDICATED" if mode == "DEDICATED" else "SHARED"
    return out


def _link_customer(db: Session, account_data: dict) -> Customer:
    """Reuse an active customer with the same phone, else create one."""
    phone = account_data["phone"].strip()
    existing = db.execute(
        select(Customer).where(Customer.phone == phone, Customer.is_active.is_(True))
    ).scalar_one_or_none()
    if existing:
        return existing

    customer = Customer(
        name=account_data["name"],
        phone=phone,
        email=(account_data.get("email") or "").strip() or None,
        notes=f"B2B partner {account_data['code']}",
        is_active=True,
    )
    db.add(customer)
    db.flush()
    return customer


def create_account(db: Session, data: dict) -> B2bAccount:
    payload = _clean_account_data(data)
    customer = _link_customer(db, payload)

    account = B2bAccount(
        code=payload["code"],
        name=payload["name"],
        kind=payload.get("kind", AccountKind.SHOP),
        gstin=(payload.get("gstin") or "").strip() or None,
        phone=payload["phone"].strip(),
        email=(payload.get("email") or "").strip() or None,
        billing_address=(payload.get("billing_address") or "").strip() or None,
        customer_id=customer.id,
        min_order_value=payload["min_order_value"],
        order_cutoff=payload["order_cutoff"],
        lead_time_hours=payload["lead_time_hours"],
        credit_days=payload["credit_days"],
        credit_limit=payload["credit_limit"],
        dispatch_days=payload["dispatch_days"],
        production_mode=payload["production_mode"],
        notes=(payload.get("notes") or "").strip() or None,
        is_active=True,
    )
    db.add(account)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Partner code '{payload['code']}' is already in use", code=payload['code']) from exc

    log_action(
        db,
        entity_type="B2bAccount",
        entity_id=account.id,
        action="CREATE",
        new_value={"code": account.code, "name": account.name},
    )
    db.commit()
    db.refresh(account)
    return account


def update_account(db: Session, account_id: int, data: dict) -> B2bAccount:
    account = get_account(db, account_id)
    payload = _clean_account_data(data)

    old = {
        "code": account.code,
        "name": account.name,
        "credit_limit": str(account.credit_limit),
        "min_order_value": str(account.min_order_value),
        "order_cutoff": account.order_cutoff,
        "dispatch_days": account.dispatch_days,
    }

    for key in (
        "code",
        "name",
        "kind",
        "phone",
        "min_order_value",
        "order_cutoff",
        "lead_time_hours",
        "credit_days",
        "credit_limit",
        "dispatch_days",
        "production_mode",
    ):
        if key in payload:
            setattr(account, key, payload[key])
    account.gstin = (payload.get("gstin") or "").strip() or None
    account.email = (payload.get("email") or "").strip() or None
    account.billing_address = (payload.get("billing_address") or "").strip() or None
    account.notes = (payload.get("notes") or "").strip() or None

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Partner code already in use") from exc

    log_action(
        db,
        entity_type="B2bAccount",
        entity_id=account.id,
        action="UPDATE",
        old_value=old,
        new_value={
            "code": account.code,
            "name": account.name,
            "credit_limit": str(account.credit_limit),
            "min_order_value": str(account.min_order_value),
            "order_cutoff": account.order_cutoff,
            "dispatch_days": account.dispatch_days,
        },
    )
    db.commit()
    db.refresh(account)
    return account


def deactivate_account(db: Session, account_id: int) -> B2bAccount:
    """Soft delete only — orders must keep pointing at the partner."""
    account = get_account(db, account_id)
    account.is_active = False
    log_action(
        db,
        entity_type="B2bAccount",
        entity_id=account.id,
        action="DELETE",
        old_value={"code": account.code, "is_active": True},
        new_value={"is_active": False},
    )
    db.commit()
    db.refresh(account)
    return account


# ===============================================================
# Contracts and price lists
# ===============================================================


def active_contract(db: Session, account_id: int, on_date: date) -> B2bContract | None:
    """The contract that governs `on_date`. Latest start wins on overlap."""
    rows = (
        db.execute(
            select(B2bContract)
            .options(selectinload(B2bContract.price_items))
            .where(B2bContract.account_id == account_id, B2bContract.is_active.is_(True))
            .order_by(B2bContract.effective_from.desc(), B2bContract.id.desc())
        )
        .scalars()
        .all()
    )
    for contract in rows:
        if contract.covers(on_date):
            return contract
    return None


def create_contract(db: Session, account_id: int, data: dict) -> B2bContract:
    account = get_account(db, account_id)

    label = (data.get("label") or "").strip()
    if not label:
        raise ValidationError("Contract label is required")

    try:
        effective_from = date.fromisoformat((data.get("effective_from") or "").strip())
    except ValueError as exc:
        raise ValidationError("Valid 'effective from' date required") from exc

    effective_to_raw = (data.get("effective_to") or "").strip()
    effective_to = None
    if effective_to_raw:
        try:
            effective_to = date.fromisoformat(effective_to_raw)
        except ValueError as exc:
            raise ValidationError("Invalid 'effective to' date") from exc
        if effective_to < effective_from:
            raise ValidationError(
                "'Effective to' cannot be before 'effective from'",
                effective_from=str(effective_from),
                effective_to=str(effective_to),
            )

    try:
        mode = PricingMode((data.get("pricing_mode") or "UNIT_PRICE").upper())
    except ValueError as exc:
        raise ValidationError("Invalid pricing mode") from exc

    pct = data.get("default_commission_pct")
    default_pct = None
    if pct not in (None, ""):
        default_pct = Decimal(str(pct))
        if not (Decimal("0") <= default_pct <= Decimal("100")):
            raise ValidationError("Commission must be between 0 and 100")
    if mode == PricingMode.COMMISSION and default_pct is None:
        raise ValidationError("A commission contract needs a default commission percentage")

    def _opt_dec(key):
        value = data.get(key)
        return None if value in (None, "") else Decimal(str(value))

    def _opt_int(key):
        value = data.get(key)
        return None if value in (None, "") else int(value)

    contract = B2bContract(
        account_id=account.id,
        label=label,
        effective_from=effective_from,
        effective_to=effective_to,
        pricing_mode=mode,
        default_commission_pct=default_pct,
        min_order_value=_opt_dec("min_order_value"),
        credit_days=_opt_int("credit_days"),
        credit_limit=_opt_dec("credit_limit"),
        terms_note=(data.get("terms_note") or "").strip() or None,
        is_active=True,
    )
    db.add(contract)
    db.flush()

    log_action(
        db,
        entity_type="B2bContract",
        entity_id=contract.id,
        action="CREATE",
        new_value={
            "account_id": account.id,
            "label": label,
            "effective_from": effective_from.isoformat(),
            "pricing_mode": mode.value,
        },
    )
    db.commit()
    db.refresh(contract)
    return contract


def get_price_item(db: Session, account_id: int, item_id: int) -> B2bPriceItem:
    item = db.get(B2bPriceItem, item_id)
    if not item or item.contract.account_id != account_id:
        raise NotFoundError(entity="Price item")
    return item


def upsert_price_item(db: Session, account_id: int, data: dict) -> B2bPriceItem:
    """Add or replace one slab. Same (contract, product, min_qty) updates in place."""
    account = get_account(db, account_id)

    contract_id = data.get("contract_id")
    if contract_id:
        contract = db.get(B2bContract, int(contract_id))
        if not contract or contract.account_id != account.id:
            raise ValidationError("Invalid contract for this partner")
    else:
        contract = active_contract(db, account.id, business_now().date())
        if contract is None:
            contract = create_contract(
                db,
                account.id,
                {
                    "label": "Standard rates",
                    "effective_from": business_now().date().isoformat(),
                    "pricing_mode": "UNIT_PRICE",
                },
            )

    try:
        product_id = int(data.get("product_id"))
        min_qty = max(1, int(data.get("min_qty") or 1))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Product and quantity are required") from exc

    unit_price = data.get("unit_price")
    commission = data.get("commission_pct")
    unit_price = None if unit_price in (None, "") else Decimal(str(unit_price))
    commission = None if commission in (None, "") else Decimal(str(commission))
    gst_rate = data.get("gst_rate")
    gst_rate = None if gst_rate in (None, "") else Decimal(str(gst_rate))

    if unit_price is None and commission is None:
        raise ValidationError("Give either a unit price or a commission percentage")
    if unit_price is not None and unit_price < 0:
        raise ValidationError("Price cannot be negative")
    if commission is not None and not (Decimal("0") <= commission <= Decimal("100")):
        raise ValidationError("Commission must be between 0 and 100")

    existing = db.execute(
        select(B2bPriceItem).where(
            B2bPriceItem.contract_id == contract.id,
            B2bPriceItem.product_id == product_id,
            B2bPriceItem.min_qty == min_qty,
        )
    ).scalar_one_or_none()

    if existing:
        existing.unit_price = unit_price
        existing.commission_pct = commission
        existing.gst_rate = gst_rate
        existing.is_active = True
        item = existing
        action = "UPDATE"
    else:
        item = B2bPriceItem(
            contract_id=contract.id,
            product_id=product_id,
            min_qty=min_qty,
            unit_price=unit_price,
            commission_pct=commission,
            gst_rate=gst_rate,
            is_active=True,
        )
        db.add(item)
        action = "CREATE"

    db.flush()
    log_action(
        db,
        entity_type="B2bPriceItem",
        entity_id=item.id,
        action=action,
        new_value={
            "account_id": account.id,
            "contract_id": contract.id,
            "product_id": product_id,
            "min_qty": min_qty,
            "unit_price": str(unit_price) if unit_price is not None else None,
            "commission_pct": str(commission) if commission is not None else None,
        },
    )
    db.commit()
    db.refresh(item)
    return item


def delete_price_item(db: Session, account_id: int, item_id: int) -> None:
    item = get_price_item(db, account_id, item_id)
    item.is_active = False
    log_action(
        db,
        entity_type="B2bPriceItem",
        entity_id=item.id,
        action="DELETE",
        new_value={"is_active": False},
    )
    db.commit()


# ===============================================================
# Price resolution
# ===============================================================


def _pct(value: Decimal) -> str:
    """Percentage for display: 30.00 -> '30'."""
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _commission_price(base_price: Decimal, pct: Decimal) -> Decimal:
    """Partner keeps `pct` of MRP; the bakery invoices the rest."""
    factor = (Decimal("100") - pct) / Decimal("100")
    return money(base_price * factor)


def _best_slab(db: Session, contract_id: int, product_id: int, qty: int) -> B2bPriceItem | None:
    """Highest slab whose lower bound the quantity reaches.

    Queried directly rather than through ``contract.price_items``: that
    collection is loaded once per session, so a rate added moments ago
    would not be visible until the session expired.
    """
    return db.execute(
        select(B2bPriceItem)
        .where(
            B2bPriceItem.contract_id == contract_id,
            B2bPriceItem.product_id == product_id,
            B2bPriceItem.is_active.is_(True),
            B2bPriceItem.min_qty <= qty,
        )
        .order_by(B2bPriceItem.min_qty.desc())
        .limit(1)
    ).scalar_one_or_none()


def resolve_price(
    db: Session,
    account: B2bAccount,
    product,
    qty: int,
    on_date: date | None = None,
) -> dict:
    """Work out what this partner pays for this product at this quantity.

    Order of precedence:
      1. the covering contract's best matching slab (unit price, else commission)
      2. the contract's mode: commission default, else retail price
      3. no contract: retail price
    """
    on_date = on_date or business_now().date()
    base_price = money(product.base_price)
    base_gst = money(product.gst_rate)

    contract = active_contract(db, account.id, on_date)
    if contract is None:
        return {
            "unit_price": base_price,
            "gst_rate": base_gst,
            "source": "RETAIL",
            "contract_id": None,
            "label": "Retail price",
        }

    slab = _best_slab(db, contract.id, product.id, qty)
    if slab is not None:
        gst_rate = money(slab.gst_rate) if slab.gst_rate is not None else base_gst
        if slab.unit_price is not None:
            return {
                "unit_price": money(slab.unit_price),
                "gst_rate": gst_rate,
                "source": "CONTRACT",
                "contract_id": contract.id,
                "label": f"Contract price ({slab.min_qty}+)",
            }
        if slab.commission_pct is not None:
            return {
                "unit_price": _commission_price(base_price, slab.commission_pct),
                "gst_rate": gst_rate,
                "source": "COMMISSION",
                "contract_id": contract.id,
                "label": f"MRP less {_pct(slab.commission_pct)}% commission",
            }

    if contract.pricing_mode == PricingMode.COMMISSION and contract.default_commission_pct is not None:
        return {
            "unit_price": _commission_price(base_price, contract.default_commission_pct),
            "gst_rate": base_gst,
            "source": "COMMISSION",
            "contract_id": contract.id,
            "label": f"MRP less {_pct(contract.default_commission_pct)}% commission",
        }

    return {
        "unit_price": base_price,
        "gst_rate": base_gst,
        "source": "RETAIL",
        "contract_id": contract.id,
        "label": "Retail price (no contract rate for this SKU)",
    }


# ===============================================================
# Credit
# ===============================================================


def outstanding(db: Session, account_id: int) -> Decimal:
    """Unpaid balance across this partner's open B2B orders."""
    total = db.execute(
        select(func.coalesce(func.sum(Order.balance_due), 0)).where(
            Order.account_id == account_id,
            Order.status != OrderStatus.CANCELLED,
            Order.balance_due > 0,
        )
    ).scalar()
    return money(Decimal(str(total or 0)))


def credit_position(
    db: Session, account: B2bAccount, extra: Decimal = Decimal("0.00")
) -> dict:
    contract = active_contract(db, account.id, business_now().date())
    limit = account.credit_limit
    if contract and contract.credit_limit is not None:
        limit = contract.credit_limit
    used = outstanding(db, account.id)
    projected = money(used + extra)
    return {
        "limit": money(limit),
        "outstanding": used,
        "projected": projected,
        "available": money(limit - projected),
        "over_limit": bool(limit > 0 and projected > limit),
        "has_limit": bool(limit > 0),
    }


# ===============================================================
# Order evaluation (quote + warnings)
# ===============================================================


def effective_terms(account: B2bAccount, contract: B2bContract | None) -> dict:
    def pick(contract_value, account_value):
        return account_value if contract_value is None else contract_value

    return {
        "min_order_value": money(
            pick(contract.min_order_value if contract else None, account.min_order_value)
        ),
        "credit_days": int(
            pick(contract.credit_days if contract else None, account.credit_days)
        ),
        "credit_limit": money(
            pick(contract.credit_limit if contract else None, account.credit_limit)
        ),
    }


def evaluate_order(
    db: Session,
    account: B2bAccount,
    items: list[dict],
    fulfillment: datetime | None = None,
    now: datetime | None = None,
) -> dict:
    """Price the lines and collect every commercial warning, without writing.

    Used by the order form's live quote and again at creation, so what the
    user sees and what gets stored cannot disagree.
    """
    from app.models import Product  # local import keeps the module import light

    now = now or business_now().replace(tzinfo=None)
    on_date = now.date()
    contract = active_contract(db, account.id, on_date)
    terms = effective_terms(account, contract)

    lines: list[dict] = []
    subtotal = Decimal("0.00")
    gst_total = Decimal("0.00")
    total = Decimal("0.00")

    for row in items:
        product = db.get(Product, int(row["product_id"]))
        if not product or not product.is_active:
            raise ValidationError(
                f"Invalid or inactive product: {row.get('product_id')}",
                product_id=row.get("product_id"),
            )
        qty = int(row.get("quantity") or 0)
        if qty <= 0:
            raise ValidationError("Quantity must be positive")

        resolved = resolve_price(db, account, product, qty, on_date)
        unit_price = resolved["unit_price"]
        gst_rate = resolved["gst_rate"]
        gst_amount = gst_for_line(unit_price, qty, gst_rate)
        line_total = line_total_with_gst(unit_price, qty, gst_amount)

        subtotal += money(unit_price * qty)
        gst_total += gst_amount
        total += line_total

        lines.append(
            {
                "product_id": product.id,
                "name": product.name,
                "sku": product.sku,
                "quantity": qty,
                "unit_price": unit_price,
                "gst_rate": gst_rate,
                "gst_amount": gst_amount,
                "line_total": line_total,
                "source": resolved["source"],
                "price_label": resolved["label"],
            }
        )

    subtotal, gst_total, total = money(subtotal), money(gst_total), money(total)

    warnings: list[str] = []

    if terms["min_order_value"] > 0 and subtotal < terms["min_order_value"]:
        warnings.append(
            f"Below the agreed minimum order value of {settings.currency}"
            f"{terms['min_order_value']:.2f} (this order is {settings.currency}{subtotal:.2f})."
        )

    cutoff = account.order_cutoff or "18:00"
    try:
        cutoff_time = time.fromisoformat(cutoff)
    except ValueError:
        cutoff_time = time(18, 0)
    if now.time() > cutoff_time:
        warnings.append(
            f"Placed after the {cutoff} cut-off — treat the dispatch date as the next "
            "working day unless agreed otherwise."
        )

    if fulfillment:
        lead_days = (account.lead_time_hours or 0) / 24
        if fulfillment < now + timedelta(days=lead_days):
            warnings.append(
                f"Fulfilment is inside the {account.lead_time_hours}h lead time for this partner."
            )
        if fulfillment.date().isoweekday() not in account.dispatch_weekdays:
            labels = ", ".join(_DOW[d] for d in sorted(account.dispatch_weekdays))
            warnings.append(
                f"That date is not a dispatch day for this partner (dispatches: {labels})."
            )

    credit = credit_position(db, account, extra=total)
    if credit["has_limit"] and credit["over_limit"]:
        warnings.append(
            f"Credit limit exceeded: {settings.currency}{credit['projected']:.2f} against a "
            f"limit of {settings.currency}{credit['limit']:.2f}."
        )
    if account.credit_days > 0 and not (account.gstin or "").strip():
        warnings.append("Partner has no GSTIN on file — the invoice will be raised without one.")

    missing = [ln["sku"] for ln in lines if ln["source"] == "RETAIL"]
    if contract is not None and missing:
        warnings.append(
            "No contract rate for: " + ", ".join(missing) + " — charged at retail price."
        )

    return {
        "lines": lines,
        "subtotal": subtotal,
        "gst_total": gst_total,
        "total": total,
        "warnings": warnings,
        "contract": contract,
        "credit": credit,
        "terms": terms,
    }


# ===============================================================
# Order terms (snapshot attached to an order)
# ===============================================================


def attach_order_terms(
    db: Session,
    order: Order,
    account: B2bAccount,
    evaluation: dict,
    po_reference: str | None = None,
    dispatch_date: date | None = None,
    payment_terms: str = "CREDIT",
) -> B2bOrderTerms:
    """Write the B2B facts for a freshly created order. No commit."""
    contract = evaluation["contract"]
    try:
        terms = PaymentTerms((payment_terms or "CREDIT").upper())
    except ValueError:
        terms = PaymentTerms.CREDIT

    credit_days = evaluation["terms"]["credit_days"]
    if terms == PaymentTerms.ADVANCE:
        credit_days = 0

    row = B2bOrderTerms(
        order_id=order.id,
        account_id=account.id,
        contract_id=contract.id if contract else None,
        po_reference=(po_reference or "").strip() or None,
        dispatch_date=dispatch_date,
        payment_terms=terms,
        credit_days=credit_days,
        production_mode=account.production_mode,
        warnings_json=json.dumps(evaluation["warnings"]),
        price_snapshot=json.dumps(
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
        ),
    )
    db.add(row)
    return row


# ===============================================================
# Statement / history
# ===============================================================


def account_orders(db: Session, account_id: int, limit: int = 50) -> list[Order]:
    return list(
        db.execute(
            select(Order)
            .where(Order.account_id == account_id)
            .order_by(Order.order_date.desc(), Order.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def statement(db: Session, account: B2bAccount, limit: int = 200) -> dict:
    """Order-level ledger for a partner: billed, received, outstanding."""
    orders = account_orders(db, account.id, limit=limit)
    rows = []
    billed = Decimal("0.00")
    received = Decimal("0.00")
    for order in orders:
        if order.status == OrderStatus.CANCELLED:
            continue
        paid = money(order.total_amount - order.balance_due)
        billed += money(order.total_amount)
        received += paid
        rows.append(
            {
                "order": order,
                "total": money(order.total_amount),
                "paid": paid,
                "balance": money(order.balance_due),
                "po": order.b2b_terms.po_reference if order.b2b_terms else None,
            }
        )
    return {
        "rows": rows,
        "billed": money(billed),
        "received": money(received),
        "outstanding": outstanding(db, account.id),
        "credit": credit_position(db, account),
    }


def margin_by_partner(db: Session, account_id: int) -> list[dict]:
    """Contract price vs recipe cost, per product, over this partner's orders.

    Cheap enough at this scale: a home bakery has tens of orders, not
    thousands. If it ever matters, aggregate in SQL.
    """
    from app.services import recipe_service

    rows = db.execute(
        select(Order)
        .where(Order.account_id == account_id, Order.status != OrderStatus.CANCELLED)
    ).scalars().all()

    agg: dict[int, dict] = {}
    for order in rows:
        for item in order.items:
            key = item.product_id
            entry = agg.setdefault(
                key,
                {
                    "product_id": key,
                    "name": item.product.name,
                    "sku": item.product.sku,
                    "quantity": 0,
                    "revenue": Decimal("0.00"),
                },
            )
            entry["quantity"] += item.quantity
            entry["revenue"] += money(item.unit_price * item.quantity)

    out = []
    for entry in agg.values():
        cost = recipe_service.recipe_cost(db, entry["product_id"]) or Decimal("0.00")
        cogs = money(cost * entry["quantity"])
        entry["cogs"] = cogs
        entry["margin"] = money(entry["revenue"] - cogs)
        entry["margin_pct"] = (
            money(entry["margin"] / entry["revenue"] * 100) if entry["revenue"] > 0 else Decimal("0")
        )
        out.append(entry)
    out.sort(key=lambda r: r["margin"], reverse=True)
    return out
