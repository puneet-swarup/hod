"""The domain layer: business vocabulary with no framework attached.

Nothing in this package may import FastAPI, Starlette, SQLAlchemy or
anything else that would tie the business rules to a transport or a
storage engine. ``tests/test_domain_exceptions.py`` enforces that.
"""

from app.domain.exceptions import (
    ConflictError,
    DomainError,
    NotFoundError,
    StateError,
    UnreachableError,
    ValidationError,
)

__all__ = [
    "DomainError",
    "ValidationError",
    "NotFoundError",
    "ConflictError",
    "StateError",
    "UnreachableError",
]
