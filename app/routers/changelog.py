"""What's new — the changelog, rendered for the people using the app.

A thin router: it reads ``CHANGELOG.md`` through the service and renders it.
No markdown library, no database, no state.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.services import changelog_service

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def whats_new(request: Request):
    templates = request.app.state.templates
    releases = changelog_service.load()

    return templates.TemplateResponse(
        request=request,
        name="changelog/index.html",
        context={
            "settings": request.app.state.settings,
            "releases": releases,
            "latest": releases[0].version if releases else "",
            "total": sum(r.item_count for r in releases),
        },
    )
