"""UI tests: repeat-order flow from customer detail."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from app.config import get_settings


def _create_order_for(app_page, live_server, seeded, select_customer, select_product, qty="2"):
    tz = ZoneInfo(get_settings().business_timezone)
    dt = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%dT12:00")

    app_page.goto(live_server + "/orders/new")
    select_customer(app_page, seeded["customer_name"])
    app_page.fill('input[name="fulfillment_date"]', dt)
    select_product(app_page, seeded["product_name"])
    app_page.fill('input[name="quantity"]', qty)
    app_page.click('button[type="submit"]')
    expect(app_page.locator("h2:has-text('Payments')")).to_be_visible(timeout=10000)


def test_repeat_button_visible_on_customer_history(app_page, seeded, live_server, select_customer, select_product):
    _create_order_for(app_page, live_server, seeded, select_customer, select_product)

    app_page.goto(live_server + f"/customers/{seeded['customer_id']}")
    expect(app_page.locator("a:has-text('Repeat')").first).to_be_visible(timeout=8000)


def test_repeat_prefills_order_form(app_page, seeded, live_server, select_customer, select_product):
    _create_order_for(app_page, live_server, seeded, select_customer, select_product, qty="3")

    app_page.goto(live_server + f"/customers/{seeded['customer_id']}")
    app_page.locator("a:has-text('Repeat')").first.click()

    # Landed on /orders/new
    assert "/orders/new" in app_page.url

    # Info banner present
    expect(app_page.locator("text=Repeating items from")).to_be_visible(timeout=5000)

    # Customer select shows the seeded customer
    selected_value = app_page.locator("#customer_id").input_value()
    assert selected_value == str(seeded["customer_id"])

    # Quantity field is 3, not the default 1
    qty_value = app_page.locator('input[name="quantity"]').first.input_value()
    assert qty_value == "3"
