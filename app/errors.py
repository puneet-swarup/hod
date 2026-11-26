"""Translation from domain failures to HTTP responses.

The single place in the application where a business rule becomes a status
code. Everything below this line is framework-free; everything above it is
HTTP.

Keeping the mapping in one table means a status code can be changed in one
line, and the domain classes never learn what a 404 is.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.domain import (
    ConflictError,
    DomainError,
    NotFoundError,
    StateError,
    UnreachableError,
    ValidationError,
)

#: The whole mapping. Ordered by specificity: subclasses first.
STATUS_BY_ERROR: dict[type[DomainError], int] = {
    ValidationError: 400,
    StateError: 400,
    NotFoundError: 404,
    ConflictError: 409,
    UnreachableError: 500,
    DomainError: 400,
}


def status_for(error: DomainError) -> int:
    """The status code for a domain error, by its most specific class.

    Walked in MRO order rather than by exact type, so a future subclass of
    ``ValidationError`` inherits 400 without being added to the table.
    """
    for cls in type(error).__mro__:
        if cls in STATUS_BY_ERROR:
            return STATUS_BY_ERROR[cls]
    return 400


def _wants_html(request: Request) -> bool:
    """True when the caller is a browser navigating, not an API client."""
    return "text/html" in request.headers.get("accept", "")


def register_domain_error_handler(app: FastAPI) -> None:
    """Attach the domain → HTTP translation to a FastAPI app.

    Called by both ``main.py`` (admin) and ``public_app.py`` (public). The
    admin app renders a page; the public app answers JSON. Both get the same
    mapping, so a rule behaves identically wherever it is triggered.
    """

    @app.exception_handler(DomainError)
    async def _domain_error_handler(request: Request, exc: DomainError) -> HTMLResponse | JSONResponse:
        status = status_for(exc)

        if _wants_html(request):
            template = "error.html" if status < 500 else "error_500.html"
            try:
                templates = request.app.state.templates
            except AttributeError:  # a bare app in a unit test
                return HTMLResponse(f"<h1>{status}</h1><p>{exc.message}</p>", status_code=status)
            return templates.TemplateResponse(
                request=request,
                name=template,
                context={
                    "settings": getattr(request.app.state, "settings", None),
                    "status": status,
                    "message": exc.message,
                    "context": exc.context,
                },
                status_code=status,
            )

        return JSONResponse(
            status_code=status,
            content={"error": type(exc).__name__, "message": exc.message},
        )


__all__ = ["register_domain_error_handler", "status_for", "STATUS_BY_ERROR"]
