"""Products as families: sizes, labels, and the bulk import.

The catalogue problem this solves: one brownie sold in five sizes used to
mean five products with the same name, so the picker showed five identical
rows and creating them meant filling the form five times.
"""

from app.models import Product
from app.services import product_service


def _product(db, name, size=None, price=100):
    return product_service.create_product(
        db,
        {
            "name": name,
            "variant_label": size,
            "base_price": price,
            "gst_rate": 5,
            "category": "Brownie",
            "pack_size": 1,
            "pack_label": "",
            "prep_time_hours": 4,
            "is_active": True,
        },
    )


def test_products_sharing_a_name_are_one_family(db):
    small = _product(db, "Nutella Brownie", "4 pc", 150)
    large = _product(db, "Nutella Brownie", "9 pc", 540)
    other = _product(db, "Ghee Nankhatai", "250 g", 150)

    assert small.family_key == large.family_key == "nutella brownie"
    assert other.family_key != small.family_key


def test_the_size_label_is_what_the_picker_shows(db):
    small = _product(db, "Nutella Brownie", "4 pc", 150)
    large = _product(db, "Nutella Brownie", "9 pc", 540)

    assert small.display_name == "Nutella Brownie · 4 pc"
    assert large.display_name == "Nutella Brownie · 9 pc"
    assert small.display_name != large.display_name


def test_size_falls_back_to_pack_then_measure(db):
    p = product_service.create_product(
        db,
        {
            "name": "Butter Cookies",
            "base_price": 220,
            "gst_rate": 5,
            "category": "Cookie",
            "pack_size": 6,
            "pack_label": "Box of 6",
            "prep_time_hours": 2,
            "is_active": True,
        },
    )
    assert p.size_label == "Box of 6"
    assert p.display_name == "Butter Cookies · Box of 6"


def test_the_order_form_picker_distinguishes_sizes(client, db):
    _product(db, "Nutella Brownie", "4 pc", 150)
    _product(db, "Nutella Brownie", "9 pc", 540)

    body = client.get("/products/search?q=nutella").text

    assert "4 pc" in body and "9 pc" in body
    assert "Nutella Brownie · 4 pc" in body
    assert "Nutella Brownie · 9 pc" in body


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------


IMPORT_ROWS = """name, size, price, gst, category
Nutella Brownie, 4 pc, 150, 5, Brownie
Nutella Brownie, 9 pc, 540, 5, Brownie
Ghee Nankhatai, 250 g, 150, 5, Cookie
"""


def test_import_creates_every_row_with_its_size(client, db):
    resp = client.post("/products/import", data={"rows": IMPORT_ROWS}, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"].endswith("imported=3")

    products = {p.display_name for p in db.query(Product).all()}
    assert products == {
        "Nutella Brownie · 4 pc",
        "Nutella Brownie · 9 pc",
        "Ghee Nankhatai · 250 g",
    }


def test_import_is_all_or_nothing(client, db):
    rows = IMPORT_ROWS + "Bad Row, 1 pc, free, 5, Brownie\n"
    resp = client.post("/products/import", data={"rows": rows})

    assert resp.status_code == 400
    assert "not a positive number" in resp.text
    # Nothing from the good rows was created either.
    assert db.query(Product).count() == 0


def test_import_needs_at_least_a_name_size_and_price(client, db):
    resp = client.post("/products/import", data={"rows": "Only a name\n"})
    assert resp.status_code == 400
    assert db.query(Product).count() == 0


def test_import_ignores_a_header_and_blank_lines(client, db):
    rows = "\nname, size, price\n\nBrownie, 4 pc, 150\n\n"
    resp = client.post("/products/import", data={"rows": rows}, follow_redirects=False)
    assert resp.status_code == 303
    assert db.query(Product).count() == 1


def test_the_product_list_counts_families(client, db):
    _product(db, "Nutella Brownie", "4 pc", 150)
    _product(db, "Nutella Brownie", "9 pc", 540)
    _product(db, "Ghee Nankhatai", "250 g", 150)

    body = client.get("/products/").text
    assert "3 sellable items in 2 products" in body


def test_the_edit_form_offers_the_other_sizes(client, db):
    small = _product(db, "Nutella Brownie", "4 pc", 150)
    _product(db, "Nutella Brownie", "9 pc", 540)

    body = client.get(f"/products/{small.id}/edit").text
    assert "is also sold in" in body
    assert "9 pc" in body
