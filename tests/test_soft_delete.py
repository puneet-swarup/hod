"""Soft delete round-trip: delete -> recreate with same phone/SKU."""

import pytest

from app.services.customer_service import create_customer, soft_delete_customer
from app.services.product_service import create_product, delete_product


def test_customer_phone_reusable_after_delete(db):
    c = create_customer(db, {"name": "A", "phone": "1111111111"})
    soft_delete_customer(db, c.id)
    c2 = create_customer(db, {"name": "B", "phone": "1111111111"})
    assert c2.id != c.id
    assert c2.is_active


def test_duplicate_active_phone_rejected(db):
    from app.domain import ConflictError

    create_customer(db, {"name": "A", "phone": "2222222222"})
    with pytest.raises(ConflictError) as exc:
        create_customer(db, {"name": "B", "phone": "2222222222"})
    # The domain names the field it rejected, without knowing about HTTP.
    assert exc.value.context["phone"] == "2222222222"


def test_product_sku_reusable_after_delete(db):
    from decimal import Decimal

    p = create_product(db, {"sku": "X-1", "name": "Old", "base_price": Decimal("10.00")})
    delete_product(db, p.id)
    p2 = create_product(db, {"sku": "X-1", "name": "New", "base_price": Decimal("12.00")})
    assert p2.id != p.id
    assert p2.is_active
