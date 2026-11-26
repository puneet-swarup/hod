"""Domain exceptions — the business's own vocabulary for failure.

This module imports **nothing**: no FastAPI, no SQLAlchemy, no app modules.
It is deliberate. The service layer raises these; the web layer translates
them into status codes. That inversion is what lets the business rules run
from a CLI, a worker or a test without an HTTP request in sight.

Rules for this module:

- Never import a framework. If this file grows an import, the design has
  failed and the guard test in ``tests/test_domain_exceptions.py`` says so.
- Never construct a response. These carry a message and structured context,
  not a status code or a JSON body.
- Add a subclass only when a caller would want to catch it specifically.
  Three near-identical subclasses are worse than one with a field.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for every business failure.

    Carries a human-readable ``message`` and optional ``context`` for the
    caller to log or surface. It knows nothing about HTTP.

    Never raise this directly — raise a subclass, so the web layer can map
    it to a sensible status without guessing.
    """

    #: Default message when a caller raises without one.
    default_message = "The request could not be completed"

    def __init__(self, message: str | None = None, **context: Any) -> None:
        self.message = message or self.default_message
        self.context: dict[str, Any] = context
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: {self.message}>"


class ValidationError(DomainError):
    """The input is wrong, or a business rule rejects it.

    Examples: a negative quantity, a price of zero, an advance larger than
    the order total, an illegal status transition.
    """

    default_message = "That value is not valid"


class NotFoundError(DomainError):
    """The thing being acted on does not exist, or is not visible."""

    default_message = "Not found"

    def __init__(self, message: str | None = None, *, entity: str = "", **context: Any) -> None:
        self.entity = entity
        if message is None and entity:
            message = f"{entity} not found"
        super().__init__(message, **context)


class ConflictError(DomainError):
    """Valid input that collides with existing state.

    Examples: a SKU already in use by an active product, a duplicate
    contract for the same partner, a numbering collision that survived a
    retry.
    """

    default_message = "That conflicts with something that already exists"


class StateError(DomainError):
    """The operation is not allowed from the object's current state.

    Example: moving an order from DELIVERED back to INQUIRY.
    """

    default_message = "That is not allowed in the current state"


class UnreachableError(DomainError):
    """A code path that should be impossible has been reached.

    Used where a retry loop falls through. If a user ever sees one of these,
    it is a bug in this codebase, not a mistake on their part — which is why
    it is a separate type rather than a generic error.
    """

    default_message = "An unexpected condition was reached"


__all__ = [
    "DomainError",
    "ValidationError",
    "NotFoundError",
    "ConflictError",
    "StateError",
    "UnreachableError",
]
