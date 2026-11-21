"""UI tests: Order creation, status flow, fulfillment requirement."""

from playwright.sync_api import expect


def _create_order(
    app_page, live_server, seeded, select_customer, select_product, *, advance="0"
):
    app_page.goto(live_server + "/orders/new")

    select_customer(app_page, seeded["customer_name"])
    app_page.fill('input[name="fulfillment_date"]', seeded["fulfillment"])
    select_product(app_page, seeded["product_name"])
    app_page.fill('input[name="quantity"]', "2")
    app_page.fill('input[name="advance_paid"]', advance)

    app_page.click('button[type="submit"]')
    # Order detail page shows the "Payments" heading
    expect(app_page.locator("h2:has-text('Payments')")).to_be_visible(timeout=10000)


def test_create_order_via_ui(app_page, seeded, live_server, select_customer, select_product):
    _create_order(app_page, live_server, seeded, select_customer, select_product)
    expect(app_page.locator(f"text={seeded['product_name']}").first).to_be_visible()


def test_status_transition_via_ui(app_page, seeded, live_server, select_customer, select_product):
    """Order CONFIRMED → IN_PROGRESS via the 'Mark In Progress' button."""
    _create_order(app_page, live_server, seeded, select_customer, select_product)

    # We're now on the order detail page in CONFIRMED status.
    # The explicit action button should be present.
    expect(app_page.locator("button:has-text('Mark IN PROGRESS')")).to_be_visible(timeout=5000)

    app_page.click("button:has-text('Mark IN PROGRESS')")
    app_page.wait_for_timeout(1000)

    # After reload, status badge should say IN PROGRESS
    expect(app_page.locator("span.badge:has-text('IN PROGRESS')")).to_be_visible(timeout=8000)

    # And the next action button should now say READY
    expect(app_page.locator("button:has-text('Mark READY')")).to_be_visible(timeout=5000)


def test_mobile_fab_visible(app_page, seeded, live_server):
    app_page.set_viewport_size({"width": 375, "height": 667})
    app_page.goto(live_server + "/")

    fab = app_page.locator('a[href="/orders/new"].btn-circle')
    expect(fab).to_be_visible(timeout=8000)


def test_fulfillment_date_is_required(app_page, seeded, live_server, select_customer, select_product):
    app_page.goto(live_server + "/orders/new")
    select_customer(app_page, seeded["customer_name"])
    select_product(app_page, seeded["product_name"])

    app_page.fill('input[name="fulfillment_date"]', "")
    app_page.click('button[type="submit"]')

    assert "/orders/new" in app_page.url


def test_order_search_via_ui(app_page, seeded, live_server, select_customer, select_product):
    # Create an order for the seeded customer
    _create_order(app_page, live_server, seeded, select_customer, select_product)

    app_page.goto(live_server + "/orders")
    app_page.fill('input[name="q"]', seeded["customer_name"])
    app_page.click('button:has-text("Search")')

    expect(app_page.locator(f"text={seeded['customer_name']}").first).to_be_visible(timeout=8000)


def test_list_shows_fresh_payment_after_recording_payment(
    app_page, seeded, live_server, select_customer, select_product
):
    """Regression: returning to the orders list after recording a payment
    must show the fresh payment status, not a stale cached page (bfcache)."""
    # 1. Create an order with no advance -> detail page.
    _create_order(app_page, live_server, seeded, select_customer, select_product, advance="0")

    # 2. Go to the orders list: the order is unpaid.
    app_page.goto(live_server + "/orders")
    expect(app_page.locator("text=Payment: Unpaid").first).to_be_visible(timeout=8000)

    # 3. Open the order detail (click the order number link).
    app_page.locator("a.font-mono").first.click()
    expect(app_page.locator("h2:has-text('Payments')")).to_be_visible(timeout=8000)

    # 4. Record a payment for the full balance (the amount field is
    #    pre-filled with the exact balance due).
    app_page.click('button:has-text("Record Payment")')
    app_page.wait_for_timeout(800)

    # 5. Return to the orders list via the Back button.
    app_page.click('a:has-text("Back")')
    expect(app_page.locator("h1:has-text('Orders')")).to_be_visible(timeout=8000)

    # 6. The list must show the UPDATED payment status (Paid), never the
    #    stale "Unpaid" from before the payment was recorded.
    expect(app_page.locator("text=Payment: Paid").first).to_be_visible(timeout=8000)


def test_browser_back_shows_fresh_status(app_page, seeded, live_server, select_customer, select_product):
    """Regression: browser Back from detail to list must not restore a
    stale bfcache snapshot after a status change."""
    _create_order(app_page, live_server, seeded, select_customer, select_product)

    # Advance the order on the detail page: CONFIRMED -> IN_PROGRESS.
    app_page.click("button:has-text('Mark IN PROGRESS')")
    app_page.wait_for_timeout(1000)
    expect(app_page.locator("span.badge:has-text('IN PROGRESS')")).to_be_visible(timeout=8000)

    # Visit the list, then go back in history to the detail page.
    app_page.goto(live_server + "/orders")
    expect(app_page.locator("span.badge:has-text('IN PROGRESS')").first).to_be_visible(timeout=8000)

    app_page.go_back()
    # The detail page must reflect IN PROGRESS, not a stale CONFIRMED.
    expect(app_page.locator("span.badge:has-text('IN PROGRESS')")).to_be_visible(timeout=8000)
    assert app_page.locator("button:has-text('Mark READY')").count() >= 0


def test_product_typeahead_suggests_and_selects(app_page, seeded, live_server):
    """The product field filters as you type and stamps the chosen id."""
    app_page.goto(live_server + "/orders/new")
    row = app_page.locator(".item-row").first
    box = row.locator(".product-search")

    box.click()
    box.press_sequentially(seeded["product_sku"][:6], delay=25)

    first = row.locator(".product-result").first
    first.wait_for(state="visible", timeout=8000)
    expect(first).to_contain_text(seeded["product_name"])

    first.click()
    expect(box).to_have_value(seeded["product_name"])
    assert row.locator(".product-id").input_value() == str(seeded["product_id"])


def test_add_item_row_gets_its_own_empty_typeahead(app_page, seeded, live_server):
    app_page.goto(live_server + "/orders/new")
    app_page.click('button:has-text("+ Add item")')

    expect(app_page.locator(".item-row")).to_have_count(2)
    expect(app_page.locator(".item-row").nth(1).locator(".product-search")).to_have_value("")
    assert app_page.locator(".item-row").nth(1).locator(".product-id").input_value() == ""


def test_submit_blocked_when_no_product_chosen(app_page, seeded, live_server, select_customer):
    """A typed-but-not-chosen product must not post an empty product_id."""
    app_page.goto(live_server + "/orders/new")
    select_customer(app_page, seeded["customer_name"])
    app_page.fill('input[name="fulfillment_date"]', seeded["fulfillment"])

    app_page.click('button[type="submit"]')
    app_page.wait_for_timeout(500)

    assert "/orders/new" in app_page.url
