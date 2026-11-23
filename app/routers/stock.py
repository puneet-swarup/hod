"""Ready stock — what is on the shelf right now, for walk-in and ad-hoc asks."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ProductMovementReason
from app.services import product_service, ready_stock_service

router = APIRouter()


def _screen_context(request: Request, db: Session) -> dict:
    products = product_service.list_products(db, include_inactive=False)
    on_hand = ready_stock_service.availability_map(db, [p.id for p in products])

    rows = []
    for product in products:
        qty = on_hand.get(product.id, 0)
        if qty == 0 and product.id not in on_hand:
            continue  # never stocked: the bake form is where it starts
        rows.append(
            {
                "product": product,
                "on_hand": qty,
                "last_bake": ready_stock_service.last_bake_at(db, product.id),
            }
        )
    rows.sort(key=lambda r: (-r["on_hand"], r["product"].name.lower()))

    return {
        "settings": request.app.state.settings,
        "rows": rows,
        "products": products,
        "summary": ready_stock_service.stock_value(db),
        "recent": _recent(db),
    }


def _recent(db: Session, limit: int = 20) -> list:
    from sqlalchemy import select

    from app.models import ProductStockMovement

    return list(
        db.execute(
            select(ProductStockMovement)
            .order_by(ProductStockMovement.created_at.desc(), ProductStockMovement.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


@router.get("/", response_class=HTMLResponse)
def stock_page(request: Request, db: Session = Depends(get_db)):
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request, name="stock/index.html", context=_screen_context(request, db)
    )


@router.post("/bake", response_class=HTMLResponse)
def bake(
    request: Request,
    db: Session = Depends(get_db),
    product_id: int = Form(...),
    quantity: int = Form(...),
    note: str = Form(""),
):
    ready_stock_service.bake(db, product_id, quantity, note.strip() or None)
    db.commit()
    return RedirectResponse(url="/stock/?baked=1", status_code=303)


@router.post("/adjust", response_class=HTMLResponse)
def adjust(
    request: Request,
    db: Session = Depends(get_db),
    product_id: int = Form(...),
    delta: int = Form(...),
    reason: str = Form("WASTAGE"),
    note: str = Form(""),
):
    try:
        reason_enum = ProductMovementReason(reason)
    except ValueError:
        reason_enum = ProductMovementReason.ADJUSTMENT
    ready_stock_service.adjust(db, product_id, delta, reason_enum, note.strip() or None)
    db.commit()
    return RedirectResponse(url="/stock/?adjusted=1", status_code=303)
