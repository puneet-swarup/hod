"""
FastAPI application entry point.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import Base, engine
from app.middleware import NoCacheMiddleware
from app.utils.time import to_business_tz

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path("data").mkdir(exist_ok=True)
    Path("data/invoices").mkdir(parents=True, exist_ok=True)
    Path(settings.backup_dir).mkdir(exist_ok=True)
    Path(settings.reports_dir).mkdir(exist_ok=True)

    from app import models  # noqa: F401

    # create_all is kept as a safety net for fresh clones before
    # `alembic upgrade head` has been run. It creates missing tables
    # but does NOT alter existing ones — Alembic handles those.
    Base.metadata.create_all(engine)

    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# No-cache headers for HTML responses
app.add_middleware(NoCacheMiddleware)

# Static files. In dev, disable caching at the mount level too.
app.mount(
    "/static",
    StaticFiles(directory="app/static", html=False),
    name="static",
)

# Jinja2 — auto_reload in dev, cached in prod.
templates = Jinja2Templates(directory="app/templates")
templates.env.auto_reload = settings.debug
templates.env.cache = {} if settings.debug else None


def _fmt_money(value) -> str:
    if value is None:
        return f"{settings.currency}0.00"
    try:
        return f"{settings.currency}{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_datetime(value, fmt: str = "%d %b %Y, %H:%M") -> str:
    if value is None:
        return ""
    local = to_business_tz(value)
    return local.strftime(fmt)


def _fmt_date(value) -> str:
    return _fmt_datetime(value, "%d %b %Y")


def _fmt_local_datetime(value, fmt: str = "%d %b %Y, %H:%M") -> str:
    """Format a naive LOCAL datetime (business wall clock) — no conversion.

    Used for values the user typed or chose (order date, fulfillment date),
    which already carry local intent. Running them through `dt` would shift
    them by +5h30m.
    """
    if value is None:
        return ""
    return value.strftime(fmt)


def _fmt_local_date(value) -> str:
    return _fmt_local_datetime(value, "%d %b %Y")


def _fmt_pct(value) -> str:
    """30.00 -> '30', 12.50 -> '12.5'. Percentages read badly with trailing zeros."""
    if value is None:
        return ""
    try:
        text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)
    return text or "0"


templates.env.filters["money"] = _fmt_money
templates.env.filters["dt"] = _fmt_datetime
templates.env.filters["d"] = _fmt_date
templates.env.filters["ldt"] = _fmt_local_datetime
templates.env.filters["ld"] = _fmt_local_date
templates.env.filters["pct"] = _fmt_pct

app.state.templates = templates
app.state.settings = settings


# --- Routers ---
# Imported after app.state is set; routers read request.app.state at call time.
from app.routers import (  # noqa: E402
    audit,
    b2b,
    customers,
    dashboard,
    export,
    ingredients,
    invoices,
    orders,
    products,
    reports,
    today,
)
from app.routers import settings as settings_router  # noqa: E402

app.include_router(dashboard.router, tags=["dashboard"])
app.include_router(today.router, tags=["today"])
app.include_router(orders.router, prefix="/orders", tags=["orders"])
app.include_router(customers.router, prefix="/customers", tags=["customers"])
app.include_router(b2b.router, prefix="/b2b", tags=["b2b"])
app.include_router(products.router, prefix="/products", tags=["products"])
app.include_router(ingredients.router, prefix="/ingredients", tags=["ingredients"])
app.include_router(invoices.router, prefix="/invoices", tags=["invoices"])
app.include_router(export.router, prefix="/export", tags=["export"])
app.include_router(reports.router, prefix="/reports", tags=["reports"])
app.include_router(audit.router, prefix="/audit", tags=["audit"])
app.include_router(settings_router.router, prefix="/settings", tags=["settings"])

from fastapi.responses import RedirectResponse


@app.get("/", include_in_schema=False)
def root():
    """Today is the home page."""
    return RedirectResponse(url="/today", status_code=307)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}


_FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<text y="52" font-size="52">🍰</text></svg>'
)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> HTMLResponse:
    return HTMLResponse(content=_FAVICON, media_type="image/svg+xml")


_SW_JS = (
    "self.addEventListener('install',e=>self.skipWaiting());"
    "self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));"
    "self.addEventListener('fetch',()=>{});"
)


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    """Minimal service worker at the root path.

    Android Chrome requires a service worker with a fetch handler before
    it offers "Install app". A no-op handler is sufficient.
    """
    return Response(content=_SW_JS, media_type="application/javascript")
