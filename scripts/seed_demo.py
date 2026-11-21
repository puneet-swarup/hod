"""
Build a demo database for training, screenshots or a sales walk-through.

It creates a small but realistic bakery: five products with recipes, three
partners on different commercial terms, a few orders in different states,
and one payment.

    python scripts/seed_demo.py --db data/demo.db

Then point the app at it:

    DB_URL=sqlite:///data/demo.db SECRET_KEY=dev uvicorn app.main:app

Safety: the script refuses to write to anything that is not clearly a demo
file. It will not touch data/bakery.db — the real one — unless you pass
--force and mean it.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

# Config is read at import time, so the target database must be set first.
_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("--db", default="data/demo.db", help="Target SQLite file")
_parser.add_argument("--force", action="store_true", help="Allow a non-demo filename")
_args = _parser.parse_args()

_target = Path(_args.db)
if "demo" not in _target.name.lower() and not _args.force:
    sys.exit(
        f"Refusing to seed {_target}: the filename does not look like a demo database.\n"
        "Use a name containing 'demo', or pass --force if you really mean it."
    )
if _target.exists():
    _target.unlink()
    for suffix in ("-wal", "-shm"):
        extra = Path(str(_target) + suffix)
        if extra.exists():
            extra.unlink()

_target.parent.mkdir(parents=True, exist_ok=True)
os.environ["DB_URL"] = f"sqlite:///{_target}"
os.environ.setdefault("SECRET_KEY", "demo-only-not-a-real-key")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("BUSINESS_TIMEZONE", "Asia/Kolkata")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.database import Base  # noqa: E402
from app.models import MovementReason  # noqa: E402
from app.services import (  # noqa: E402
    b2b_service,
    inventory_service,
    order_service,
    recipe_service,
)
from app.services.product_service import create_product  # noqa: E402
from app.utils.time import business_now  # noqa: E402


def main() -> None:
    engine = create_engine(f"sqlite:///{_target}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # --- Products -------------------------------------------------------
    products = {}
    for sku, name, price, category, prep in [
        ("CHOC-500", "Chocolate Truffle Cake", "850.00", "Cake", 6),
        ("BLACK-1KG", "Black Forest Cake", "950.00", "Cake", 6),
        ("BROWNIE-9", "Fudge Brownie Box (9)", "450.00", "Brownie", 3),
        ("COOKIE-250", "Butter Cookies 250g", "220.00", "Cookie", 2),
        ("PASTRY-6", "Assorted Pastry Box (6)", "540.00", "Pastry", 4),
    ]:
        products[sku] = create_product(
            db,
            {
                "sku": sku,
                "name": name,
                "base_price": Decimal(price),
                "gst_rate": Decimal("5.00"),
                "category": category,
                "prep_time_hours": prep,
            },
        )

    # --- Ingredients and recipes (so cost and margin are real) ----------
    ingredients = {}
    for name, unit, cost, threshold, opening in [
        ("Dark chocolate", "g", "0.85", "2000", "20000"),
        ("Refined flour", "g", "0.06", "10000", "20000"),
        ("Sugar", "g", "0.05", "10000", "20000"),
        ("Butter", "g", "0.55", "5000", "20000"),
        ("Fresh cream", "ml", "0.32", "3000", "20000"),
        ("Eggs", "pcs", "7.00", "60", "200"),
    ]:
        ing = inventory_service.create_ingredient(
            db,
            {
                "name": name,
                "unit": unit,
                "kind": "RAW",
                "cost_per_unit": Decimal(cost),
                "reorder_threshold": Decimal(threshold),
            },
        )
        ingredients[name] = ing
        inventory_service.record_movement(
            db,
            ing.id,
            delta=Decimal(opening),
            reason=MovementReason.PURCHASE,
            unit_cost=Decimal(cost),
        )

    recipes = {
        "CHOC-500": [
            ("Dark chocolate", 250),
            ("Refined flour", 150),
            ("Sugar", 180),
            ("Butter", 120),
            ("Fresh cream", 150),
            ("Eggs", 3),
        ],
        "BLACK-1KG": [
            ("Refined flour", 300),
            ("Sugar", 350),
            ("Butter", 200),
            ("Fresh cream", 300),
            ("Eggs", 6),
        ],
        "BROWNIE-9": [
            ("Dark chocolate", 180),
            ("Refined flour", 200),
            ("Sugar", 250),
            ("Butter", 180),
            ("Eggs", 3),
        ],
        "COOKIE-250": [("Refined flour", 180), ("Sugar", 90), ("Butter", 120)],
        "PASTRY-6": [
            ("Refined flour", 200),
            ("Sugar", 150),
            ("Butter", 150),
            ("Fresh cream", 200),
            ("Eggs", 4),
        ],
    }
    for sku, lines in recipes.items():
        recipe_service.replace_recipe(
            db,
            products[sku].id,
            [
                {"ingredient_id": ingredients[name].id, "quantity_per_unit": qty}
                for name, qty in lines
            ],
        )

    today = business_now().date()

    # --- Partner 1: unit price, credit -----------------------------------
    sweet = b2b_service.create_account(
        db,
        {
            "code": "SWEET-BAN",
            "name": "Sweet Corner Bandra",
            "kind": "SHOP",
            "phone": "9820011223",
            "email": "accounts@sweetcorner.in",
            "gstin": "27ABCDE1234F1Z5",
            "billing_address": "Shop 4, Linking Road, Bandra West, Mumbai 400050",
            "min_order_value": "2000",
            "order_cutoff": "18:00",
            "lead_time_hours": "24",
            "credit_days": "15",
            "credit_limit": "20000",
            "dispatch_days": ["1", "2", "3", "4", "5", "6"],
            "notes": "Deliver before 11 am. Call Rajesh on arrival.",
        },
    )
    sweet_contract = b2b_service.create_contract(
        db,
        sweet.id,
        {
            "label": "FY27 rates",
            "effective_from": (today - timedelta(days=30)).isoformat(),
            "pricing_mode": "UNIT_PRICE",
        },
    )
    for sku, slabs in {
        "CHOC-500": [(1, "780.00"), (10, "740.00")],
        "BLACK-1KG": [(1, "870.00")],
        "BROWNIE-9": [(1, "400.00"), (20, "380.00")],
        "COOKIE-250": [(1, "190.00")],
    }.items():
        for min_qty, price in slabs:
            b2b_service.upsert_price_item(
                db,
                sweet.id,
                {
                    "contract_id": sweet_contract.id,
                    "product_id": products[sku].id,
                    "min_qty": min_qty,
                    "unit_price": price,
                },
            )

    # --- Partner 2: commission ------------------------------------------
    junction = b2b_service.create_account(
        db,
        {
            "code": "CAKE-POWAI",
            "name": "Cake Junction, Powai",
            "kind": "FRANCHISEE",
            "phone": "9822033445",
            "email": "orders@cakejunction.in",
            "gstin": "27PQRSX5678G1Z2",
            "billing_address": "Hiranandani Gardens, Powai, Mumbai 400076",
            "min_order_value": "1500",
            "order_cutoff": "17:00",
            "lead_time_hours": "24",
            "credit_days": "30",
            "credit_limit": "30000",
            "dispatch_days": ["1", "3", "5"],
        },
    )
    franchise_contract = b2b_service.create_contract(
        db,
        junction.id,
        {
            "label": "Franchise agreement 2026-27",
            "effective_from": (today - timedelta(days=60)).isoformat(),
            "pricing_mode": "COMMISSION",
            "default_commission_pct": "25",
        },
    )
    b2b_service.upsert_price_item(
        db,
        junction.id,
        {
            "contract_id": franchise_contract.id,
            "product_id": products["PASTRY-6"].id,
            "commission_pct": "35",
        },
    )

    # --- Partner 3: no contract yet (falls back to retail) --------------
    thane = b2b_service.create_account(
        db,
        {
            "code": "DESSERT-THANE",
            "name": "Dessert Hub, Thane",
            "kind": "SHOP",
            "phone": "9823044556",
            "billing_address": "Ghodbunder Road, Thane West 400607",
            "min_order_value": "1000",
            "order_cutoff": "18:00",
            "lead_time_hours": "12",
            "credit_days": "7",
            "credit_limit": "0",
            "dispatch_days": ["1", "2", "3", "4", "5", "6", "7"],
        },
    )

    def order(partner, items, days=2, po=None, pay="0"):
        return order_service.create_order(
            db,
            {
                "account_id": partner.id,
                "items": items,
                "fulfillment_date": (business_now() + timedelta(days=days)).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "po_reference": po,
                "payment_terms": "CREDIT",
                "advance_paid": pay,
                "advance_method": "UPI",
            },
        )

    first = order(
        sweet,
        [
            {"product_id": products["CHOC-500"].id, "quantity": 12},
            {"product_id": products["BROWNIE-9"].id, "quantity": 24},
        ],
        days=1,
        po="PO-2291",
    )
    second = order(
        sweet,
        [{"product_id": products["BLACK-1KG"].id, "quantity": 4}],
        days=3,
        po="PO-2292",
    )
    order(
        junction,
        [
            {"product_id": products["PASTRY-6"].id, "quantity": 10},
            {"product_id": products["COOKIE-250"].id, "quantity": 20},
        ],
        days=2,
        po="CJ-8891",
    )
    order(thane, [{"product_id": products["COOKIE-250"].id, "quantity": 5}], days=2)

    order_service.record_payment(db, second.id, Decimal("2000.00"), "BANK", "NEFT-9931")
    order_service.update_status(db, first.id, "IN_PROGRESS")

    db.close()
    engine.dispose()

    print(f"Demo database ready: {_target}")
    print("  3 partners · 5 products with recipes · 4 B2B orders · 1 payment")
    print()
    print("Run the app against it:")
    print(f"  DB_URL=sqlite:///{_target} SECRET_KEY=demo uvicorn app.main:app")
    print()
    print("Then open /b2b to start the walk-through.")


if __name__ == "__main__":
    main()
