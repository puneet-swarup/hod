"""Domain exceptions and their HTTP translation.

Two halves, both cheap to test:

- ``app/domain/exceptions.py`` is pure Python. These tests need no
  fixtures, no database and no client.
- ``app/errors.py`` maps them to status codes. Tested through a tiny app,
  not the real one, so the mapping is proven independently of routing.

The guard test at the bottom is the one that matters most: it fails if the
domain layer ever imports a framework again.
"""

import ast
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain import (
    ConflictError,
    DomainError,
    NotFoundError,
    StateError,
    UnreachableError,
    ValidationError,
)
from app.errors import STATUS_BY_ERROR, register_domain_error_handler, status_for

# ---------------------------------------------------------------------------
# The exceptions themselves
# ---------------------------------------------------------------------------


def test_a_message_is_carried_through():
    err = ValidationError("Quantity must be positive")
    assert err.message == "Quantity must be positive"
    assert str(err) == "Quantity must be positive"


def test_each_type_has_a_sensible_default_message():
    assert ValidationError().message
    assert ConflictError().message
    assert StateError().message
    assert UnreachableError().message


def test_not_found_builds_its_message_from_the_entity():
    err = NotFoundError(entity="Order")
    assert err.message == "Order not found"
    assert err.entity == "Order"


def test_not_found_prefers_an_explicit_message():
    err = NotFoundError("Order 42 is not yours", entity="Order")
    assert err.message == "Order 42 is not yours"


def test_context_is_captured_for_the_caller():
    err = ConflictError("SKU in use", sku="BROWNIE-9")
    assert err.context == {"sku": "BROWNIE-9"}


def test_repr_names_the_type():
    assert "ValidationError" in repr(ValidationError("bad"))


def test_the_base_class_is_not_meant_to_be_raised():
    """It exists to be caught, not thrown — the mapping covers it anyway."""
    assert status_for(DomainError("anything")) == 400


# ---------------------------------------------------------------------------
# The mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ValidationError("x"), 400),
        (StateError("x"), 400),
        (NotFoundError("x"), 404),
        (ConflictError("x"), 409),
        (UnreachableError("x"), 500),
    ],
)
def test_each_error_maps_to_its_status(error, expected):
    assert status_for(error) == expected


def test_a_subclass_inherits_its_parent_status():
    class SpecialValidationError(ValidationError):
        pass

    assert status_for(SpecialValidationError("x")) == 400


def test_every_mapped_class_is_a_domain_error():
    for cls in STATUS_BY_ERROR:
        assert issubclass(cls, DomainError)


# ---------------------------------------------------------------------------
# Through an app — JSON for API clients, HTML for browsers
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_with_handler():
    app = FastAPI()
    register_domain_error_handler(app)

    @app.get("/boom/{kind}")
    def boom(kind: str):
        raise {
            "validation": ValidationError("Quantity must be positive"),
            "notfound": NotFoundError(entity="Order"),
            "conflict": ConflictError("SKU in use", sku="A-1"),
            "state": StateError("Cannot go back"),
            "unreachable": UnreachableError("Retry loop fell through"),
        }[kind]

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        ("validation", 400),
        ("notfound", 404),
        ("conflict", 409),
        ("state", 400),
        ("unreachable", 500),
    ],
)
def test_the_app_returns_the_mapped_status(app_with_handler, kind, status):
    resp = app_with_handler.get(f"/boom/{kind}", headers={"accept": "application/json"})
    assert resp.status_code == status


def test_an_api_client_gets_json(app_with_handler):
    resp = app_with_handler.get("/boom/conflict", headers={"accept": "application/json"})
    body = resp.json()
    assert body["error"] == "ConflictError"
    assert body["message"] == "SKU in use"


def test_a_browser_gets_html(app_with_handler):
    resp = app_with_handler.get("/boom/notfound", headers={"accept": "text/html"})
    assert resp.status_code == 404
    # No templates attached in this bare app, so the fallback renders.
    assert "Order not found" in resp.text


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


FORBIDDEN = {"fastapi", "starlette", "sqlalchemy", "jinja2", "alembic"}


def test_the_domain_layer_imports_no_framework():
    """The whole point of this refactor, enforced rather than promised.

    If someone adds ``from fastapi import HTTPException`` to a domain module,
    this fails before it can spread.
    """
    domain_dir = pathlib.Path("app/domain")
    offenders: list[str] = []

    for path in domain_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for name in names:
                if name in FORBIDDEN:
                    offenders.append(f"{path}: imports {name}")

    assert not offenders, "The domain layer must stay framework-free:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# M2 — customer_service is the reference implementation
# ---------------------------------------------------------------------------


def test_customer_service_raises_domain_errors_not_http(db):
    """The service layer is framework-free: its failures are domain types."""
    from app.domain import ConflictError, NotFoundError
    from app.services.customer_service import create_customer, get_customer

    with pytest.raises(NotFoundError) as exc:
        get_customer(db, 999_999)
    assert exc.value.entity == "Customer"

    create_customer(db, {"name": "A", "phone": "9000000001"})
    with pytest.raises(ConflictError):
        create_customer(db, {"name": "B", "phone": "9000000001"})


def test_a_domain_error_reaches_the_browser_as_a_page(client, db):
    """The mapping works end to end, not just in the unit above."""
    resp = client.get("/customers/999999", headers={"accept": "text/html"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# M7 — the guard that keeps the refactor from unravelling
# ---------------------------------------------------------------------------


def test_no_service_raises_http_exceptions():
    """The service layer must not know HTTP exists.

    Checked by parsing the source rather than importing, so a raise hidden
    behind a conditional is still caught. This is the test that stops the
    old pattern creeping back one shortcut at a time.
    """
    offenders: list[str] = []

    for path in pathlib.Path("app/services").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                if any("fastapi" in n for n in names):
                    offenders.append(f"{path}: imports fastapi")

    assert not offenders, "Services must raise domain errors, not HTTP:\n" + "\n".join(offenders)


def test_every_service_module_imports_cleanly_without_http():
    """Importing the service layer must not require FastAPI to be present.

    Proves the inversion is real rather than cosmetic: the modules are
    loaded with FastAPI blocked from the import system.
    """
    import builtins
    import importlib
    import sys

    blocked = {"fastapi", "starlette"}
    real_import = builtins.__import__
    saved = {name: sys.modules.pop(name) for name in list(sys.modules) if name.split(".")[0] in blocked}

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in blocked:
            raise ImportError(f"{name} is blocked for this test")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = guarded
    try:
        for module in (
            "app.services.customer_service",
            "app.services.product_service",
            "app.services.recipe_service",
            "app.services.inventory_service",
            "app.services.ready_stock_service",
            "app.services.invoice_service",
            "app.services.order_service",
            "app.services.b2b_service",
        ):
            sys.modules.pop(module, None)
            importlib.import_module(module)
    finally:
        builtins.__import__ = real_import
        sys.modules.update(saved)
