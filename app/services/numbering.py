"""
Numbering service. Provides gapless, monotonic document numbers.

Concurrency:
- On SQLite with WAL and busy_timeout, writers serialize. The
  `with_for_update()` hint is a no-op on SQLite but correct on
  Postgres if you migrate.
- The prefix row is created on first use.
- If two transactions race and both read the same last_value, the
  second insert/update will fail on the primary key of NumberSequence
  or a subsequent unique constraint. Callers should retry once.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.number_sequence import NumberSequence
from app.utils.time import business_now


def _prefix(kind: str) -> str:
    settings = get_settings()
    year = business_now().year
    return f"{settings.invoice_prefix}-{year}-{kind}"


def next_order_number(db: Session) -> str:
    return _next(db, "ORDER")


def next_invoice_number(db: Session) -> str:
    return _next(db, "INVOICE")


def next_b2b_order_number(db: Session) -> str:
    """B2B orders get their own series, so a partner's paperwork is separate.

    Format: HOD-B2B-2026-0001 (fits orders.order_number VARCHAR(20)).
    Retail numbering is untouched — existing numbers never shift.
    """
    settings = get_settings()
    seq = _bump(db, _prefix("B2BORDER"))
    return f"{settings.invoice_prefix}-B2B-{business_now().year}-{seq:04d}"


def _bump(db: Session, prefix: str) -> int:
    """Increment and return the next sequence value for `prefix`."""
    row = db.execute(
        select(NumberSequence).where(NumberSequence.prefix == prefix).with_for_update()
    ).scalar_one_or_none()

    if row is None:
        row = NumberSequence(prefix=prefix, last_value=0)
        db.add(row)
        db.flush()

    row.last_value += 1
    db.flush()
    return row.last_value


def _next(db: Session, kind: str) -> str:
    # Format: HOD-2026-0001 (kind is embedded in prefix but not in the
    # human-readable number, matching v0.1 behaviour).
    seq = _bump(db, _prefix(kind))
    settings = get_settings()
    year = business_now().year
    return f"{settings.invoice_prefix}-{year}-{seq:04d}"
