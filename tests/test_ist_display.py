"""Timestamps that are stored as naive UTC must be *displayed* in IST.

Storage policy (app/utils/time.py): the database holds naive UTC; the
business timezone (Asia/Kolkata) is applied only at the display boundary
via the `dt` / `d` Jinja filters. A template that calls strftime() on the
raw value silently shows UTC — 5h30m behind what the user's wall clock
says. These tests pin the display behaviour.
"""

from datetime import datetime

from app.models import AuditLog


def _utc(*args) -> datetime:
    return datetime(*args)  # naive UTC, exactly as stored


def test_audit_page_shows_ist_not_utc(client, db):
    # 09:00 UTC == 14:30 IST on the same day.
    db.add(
        AuditLog(
            entity_type="Order",
            entity_id=1,
            action="CREATE",
            changed_at=_utc(2026, 11, 21, 9, 0),
            changed_by="system",
        )
    )
    db.commit()

    body = client.get("/audit").text
    assert "21 Nov 14:30" in body
    assert "21 Nov 09:00" not in body


def test_audit_page_handles_utc_day_boundary(client, db):
    # 20:15 UTC on 20 Nov == 01:45 IST on 21 Nov.
    db.add(
        AuditLog(
            entity_type="Order",
            entity_id=2,
            action="CREATE",
            changed_at=_utc(2026, 11, 20, 20, 15),
            changed_by="system",
        )
    )
    db.commit()

    body = client.get("/audit").text
    assert "21 Nov 01:45" in body
    assert "20 Nov 20:15" not in body


def test_dt_filter_converts_utc_to_ist():
    from app.main import _fmt_datetime

    assert _fmt_datetime(_utc(2026, 11, 21, 9, 0)) == "21 Nov 2026, 14:30"
    assert _fmt_datetime(_utc(2026, 11, 21, 9, 0), "%H:%M") == "14:30"


def test_dt_filter_passes_none_through():
    from app.main import _fmt_datetime

    assert _fmt_datetime(None) == ""


def test_reports_list_converts_file_mtime_to_utc(tmp_path, monkeypatch):
    """Report mtimes are POSIX timestamps; they must come back as naive UTC
    so the template's `dt` filter lands on IST (not a second shift)."""
    from app.config import get_settings
    from app.services import reports_service

    (tmp_path / "2026-09.pdf").write_bytes(b"x")
    monkeypatch.setattr(get_settings(), "reports_dir", str(tmp_path))

    rows = reports_service.list_existing_reports()
    assert len(rows) == 1
    assert rows[0]["generated_at"].tzinfo is None
