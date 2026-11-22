"""UI tests: order detail page — COGS, cancel flow, action buttons."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from app.config import get_settings


def _create_order(app_page, live_server, seeded, select_customer, select_product):
    tz = ZoneInfo(get_settings().business_timezone)
    dt = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%dT12:00")

    app_page.goto(live_server + "/orders/new")
    select_customer(app_page, seeded["customer_name"])
    app_page.fill('input[name="fulfillment_date"]', dt)
    select_product(app_page, seeded["product_name"])
    app_page.fill('input[name="quantity"]', "1")
    app_page.click('button[type="submit"]')
    expect(app_page.locator("h2:has-text('Payments')")).to_be_visible(timeout=10000)


def test_confirmed_order_shows_forward_and_cancel(app_page, seeded, live_server, select_customer, select_product):
    _create_order(app_page, live_server, seeded, select_customer, select_product)
    # CONFIRMED: forward button says IN PROGRESS, cancel button present
    expect(app_page.locator("button:has-text('Mark IN PROGRESS')")).to_be_visible(timeout=5000)
    expect(app_page.locator("button:has-text('Cancel')").first).to_be_visible()


def test_in_progress_shows_two_cancel_variants(app_page, seeded, live_server, select_customer, select_product):
    _create_order(app_page, live_server, seeded, select_customer, select_product)

    # Move to IN_PROGRESS
    app_page.click("button:has-text('Mark IN PROGRESS')")
    app_page.wait_for_timeout(1000)

    # Now the two cancel variants should be visible
    expect(app_page.locator("button:has-text('Cancel · return stock')")).to_be_visible(timeout=5000)
    expect(app_page.locator("button:has-text('Cancel · waste')")).to_be_visible(timeout=5000)
    # And the forward action is READY
    expect(app_page.locator("button:has-text('Mark READY')")).to_be_visible()


def test_delivered_order_has_no_cancel(app_page, seeded, live_server, select_customer, select_product):
    """DELIVERED is not cancellable — no Cancel button in the main content."""
    _create_order(app_page, live_server, seeded, select_customer, select_product)

    app_page.click("button:has-text('Mark IN PROGRESS')")
    app_page.wait_for_timeout(1000)
    app_page.click("button:has-text('Mark READY')")
    app_page.wait_for_timeout(1000)
    app_page.click("button:has-text('Mark DELIVERED')")
    app_page.wait_for_timeout(1000)

    # DELIVERED is the terminal success state — no further forward action.
    expect(app_page.locator("span.badge:has-text('DELIVERED')")).to_be_visible(timeout=5000)
    assert app_page.locator("button:has-text('Mark PAID')").count() == 0

    # No Cancel button inside main (modals live outside main and don't count)
    cancel_in_main = app_page.locator("main button:has-text('Cancel')")
    assert cancel_in_main.count() == 0, (
        f"DELIVERED order should not offer Cancel in main content. "
        f"Found {cancel_in_main.count()} matching buttons."
    )


def test_cogs_displayed_when_recipe_and_stock_exist(app_page, seeded, live_server, select_customer, select_product):
    """
    When the seeded product has a recipe and ingredients on hand, moving
    to IN_PROGRESS deducts, and order detail shows Ingredient cost.
    """
    # Create an ingredient with stock
    app_page.goto(live_server + "/ingredients/new")
    app_page.fill('input[name="name"]', "Detail Cost Ingredient")
    app_page.select_option('select[name="unit"]', "g")
    app_page.fill('input[name="reorder_threshold"]', "0")
    app_page.fill('input[name="initial_stock"]', "1000")
    app_page.fill('input[name="initial_stock_cost"]', "0.50")
    app_page.click('button[type="submit"]')
    expect(app_page.locator("h1")).to_be_visible(timeout=8000)

    # Add a recipe line to the seeded product
    pid = seeded["product_id"]
    app_page.goto(live_server + f"/products/{pid}/recipe")
    app_page.select_option('select[name="ingredient_id"]', label="Detail Cost Ingredient (g)")
    app_page.fill('input[name="quantity"]', "100")
    app_page.click('button[type="submit"]')
    expect(app_page.locator("text=Recipe saved")).to_be_visible(timeout=8000)

    # Create order and move to IN_PROGRESS
    _create_order(app_page, live_server, seeded, select_customer, select_product)
    app_page.click("button:has-text('Mark IN PROGRESS')")
    app_page.wait_for_timeout(1200)

    # COGS block should now appear
    expect(app_page.locator("text=Ingredient cost")).to_be_visible(timeout=8000)
    expect(app_page.locator("text=Gross margin")).to_be_visible()
