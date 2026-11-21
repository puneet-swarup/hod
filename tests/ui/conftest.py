"""
Playwright UI test fixtures.

Architecture:
- The app server runs in a SUBPROCESS with its own env. This is
  deliberate: importing the app in-process would fight with the
  root tests/conftest.py over sys.modules and the DB engine.
- The UI test DB is a real SQLite file (data/test_ui.db), wiped once
  per session, seeded by direct SQLAlchemy connection.
- Tests navigate explicitly: page.goto(live_server + "/path").
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

TEST_PORT = 8765
TEST_DB = Path("data/test_ui.db").resolve()
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def _wait_for_port(host: str, port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(host, port):
            return
        time.sleep(0.2)
    raise RuntimeError(f"Server did not open port {port} within {timeout}s")


# ---------------------------------------------------------------
# Live server (session scope, subprocess)
# ---------------------------------------------------------------


@pytest.fixture(scope="session")
def live_server():
    # Wipe any previous test DB
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(TEST_DB) + suffix)
        if p.exists():
            p.unlink()

    TEST_DB.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["DB_URL"] = f"sqlite:///{TEST_DB}"
    env["SECRET_KEY"] = "ui-test-secret"
    env["DEBUG"] = "false"
    env["BUSINESS_TIMEZONE"] = "Asia/Kolkata"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(TEST_PORT),
            "--log-level",
            "warning",
            "--no-access-log",
        ],
        env=env,
        cwd=str(Path.cwd()),
    )

    try:
        _wait_for_port("127.0.0.1", TEST_PORT, timeout=25)
    except RuntimeError:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise

    yield BASE_URL

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)

    # Windows can hold file handles briefly after process exit.
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(TEST_DB) + suffix)
        for _ in range(10):
            try:
                if p.exists():
                    p.unlink()
                break
            except PermissionError:
                time.sleep(0.3)


# ---------------------------------------------------------------
# Seeded data (function scope)
# ---------------------------------------------------------------


@pytest.fixture()
def seeded(live_server):
    """
    Wipe domain tables and insert one customer + one product.
    Returns a dict with IDs and names so tests can reference them.
    """
    from zoneinfo import ZoneInfo

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.config import get_settings
    from app.database import Base
    from app.models import (  # noqa: F401
        Address,
        Customer,
        Invoice,
        Order,
        OrderItem,
        Payment,
        Product,
    )

    engine = create_engine(f"sqlite:///{TEST_DB}")
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        for model in (Invoice, Payment, OrderItem, Order, Address, Customer, Product):
            db.query(model).delete()
        db.commit()

        # Numeric suffix so phone normalization works
        import uuid as _uuid

        num = _uuid.uuid4().int % 100000
        suffix = f"{num:05d}"

        c = Customer(
            name=f"UI Customer {suffix}",
            phone=f"90000{suffix}",  # 10 digits, no letters
            email=None,
            is_active=True,
        )
        db.add(c)
        db.commit()
        db.refresh(c)

        p = Product(
            sku=f"UI-CAKE-{suffix}",
            name=f"UI Test Cake {suffix}",
            category="Cake",
            base_price=350,
            gst_rate=5,
            prep_time_hours=4,
            is_active=True,
        )
        db.add(p)
        db.commit()
        db.refresh(p)

        # Tomorrow at 12:00 in the BUSINESS timezone, not the runner's.
        tz = ZoneInfo(get_settings().business_timezone)
        fulfillment = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%dT12:00")

        yield {
            "customer_id": c.id,
            "customer_name": c.name,
            "customer_phone": c.phone,
            "product_id": p.id,
            "product_name": p.name,
            "product_sku": p.sku,
            "fulfillment": fulfillment,
        }
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------
# Convenience: page already navigated to /
# ---------------------------------------------------------------


@pytest.fixture()
def app_page(browser, live_server):
    """A fresh page pointed at the app root."""
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(10000)
    page.goto(live_server + "/")
    yield page


# ---------------------------------------------------------------
# Shared UI actions
# ---------------------------------------------------------------


@pytest.fixture()
def select_customer():
    """Return a callable that picks a customer via the order-form typeahead.

    Types the name into the search box, waits for the HTMX-filtered
    result list, and clicks the matching row. This exercises the real
    search path instead of the old static <select>.
    """

    def _select(page, name: str) -> None:
        # Use per-character typing so real keyup events fire — the form's
        # hx-trigger is "keyup changed delay:300ms", which fill() does not
        # trigger (fill sets the value and fires only an input event).
        box = page.locator("#customer-search")
        box.click()
        box.press_sequentially(name, delay=30)
        page.wait_for_selector(".customer-result", timeout=8000)
        page.click(f'.customer-result:has-text("{name}")')
        page.wait_for_function(
            "document.getElementById('customer_id').value !== ''",
            timeout=5000,
        )

    return _select


@pytest.fixture()
def select_product():
    """Return a callable that picks a product via the order-form type-ahead.

    Types into the item row's search box, waits for the HTMX-filtered
    suggestion list and clicks the first match — the real search path,
    not the old static <select>.
    """

    def _select(page, name: str, row_index: int = 0) -> None:
        row = page.locator(".item-row").nth(row_index)
        box = row.locator(".product-search")
        box.click()
        # Per-character typing so the "keyup changed" trigger fires.
        box.press_sequentially(name, delay=30)
        row.locator(".product-result").first.wait_for(state="visible", timeout=8000)
        row.locator(".product-result").first.click()
        page.wait_for_function(
            "document.querySelectorAll('.item-row')[" + str(row_index) + "]"
            ".querySelector('.product-id').value !== ''",
            timeout=5000,
        )

    return _select
