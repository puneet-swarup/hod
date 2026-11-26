"""The changelog parser and the What's new page.

The parser is deliberately narrow: it reads the markdown this project writes
and nothing else. These tests pin that contract, so a changelog that grows a
new construct fails loudly instead of rendering as a wall of text.
"""

from pathlib import Path

import pytest

from app.services import changelog_service as cl

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

SAMPLE = """# What's new

Some preamble that a reader browsing the file sees, but the page does not.

---

## v1.2 — 26 November 2026

### Added
- **Costing.** A recipe per family.
- Bulk entry.

### Fixed
- The nav link was missing.

## v1.1 — 23 November 2026

### Added
- Ready stock.
"""


def test_releases_are_read_in_file_order():
    releases = cl.parse(SAMPLE)
    assert [r.version for r in releases] == ["v1.2", "v1.1"]


def test_the_version_and_date_are_split():
    release = cl.parse(SAMPLE)[0]
    assert release.version == "v1.2"
    assert release.date == "26 November 2026"


@pytest.mark.parametrize(
    "label",
    ["v2.0 — 1 Jan 2027", "v2.0 – 1 Jan 2027", "v2.0 - 1 Jan 2027", "v2.0 · 1 Jan 2027"],
)
def test_every_dash_a_person_might_type_works(label):
    """An em dash, an en dash, a hyphen and a middot all split correctly."""
    release = cl.parse(f"## {label}\n### Added\n- thing\n")[0]
    assert release.version == "v2.0"
    assert release.date == "1 Jan 2027"


def test_a_release_with_no_date_still_parses():
    release = cl.parse("## v1.0\n### Added\n- thing\n")[0]
    assert release.version == "v1.0"
    assert release.date == ""


def test_groups_keep_their_order_and_items():
    release = cl.parse(SAMPLE)[0]
    assert [g.label for g in release.groups] == ["Added", "Fixed"]
    assert len(release.groups[0].items) == 2
    assert release.groups[0].items[0].startswith("**Costing.**")


def test_the_preamble_is_ignored():
    """Text before the first release is for a reader of the file, not the page."""
    releases = cl.parse(SAMPLE)
    assert all("preamble" not in item for r in releases for g in r.groups for item in g.items)


def test_a_bullet_before_any_heading_lands_in_a_default_group():
    release = cl.parse("## v1.0\n- a stray bullet\n")[0]
    assert release.groups[0].label == "Changed"
    assert release.groups[0].items == ["a stray bullet"]


def test_prose_between_bullets_is_ignored():
    release = cl.parse("## v1.0\n### Added\n- one\n\nSome prose.\n\n- two\n")[0]
    assert release.groups[0].items == ["one", "two"]


def test_item_count_adds_up():
    release = cl.parse(SAMPLE)[0]
    assert release.item_count == 3


def test_an_empty_document_yields_no_releases():
    assert cl.parse("") == []
    assert cl.parse("# What's new\n\nNothing yet.\n") == []


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_a_missing_file_is_an_empty_list_not_a_crash(tmp_path):
    """A fresh checkout has no changelog; the page says so rather than failing."""
    assert cl.load(tmp_path / "nope.md") == []


def test_the_real_changelog_parses(tmp_path):
    """The file this project actually ships must satisfy the parser."""
    releases = cl.load()
    assert releases, "CHANGELOG.md should exist and contain releases"
    assert all(r.version for r in releases), "every release should carry a version"
    assert all(r.groups for r in releases), "every release should carry at least one group"


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def test_the_page_lists_the_releases(client, db):
    body = client.get("/whats-new").text
    assert "What's new" in body
    latest = cl.load()[0]
    assert latest.version in body


def test_the_page_shows_a_release_heading_and_items(client, db):
    releases = cl.load()
    assert releases[0].groups[0].items[0][:20].replace("**", "") in client.get("/whats-new").text


def test_the_navigation_links_to_whats_new(client, db):
    assert 'href="/whats-new"' in client.get("/today").text


def test_the_page_says_so_when_there_is_no_changelog(client, db, monkeypatch):
    monkeypatch.setattr(cl, "load", lambda path=None: [])
    body = client.get("/whats-new").text
    assert "No changelog found" in body


def test_a_wrapped_bullet_keeps_its_whole_text():
    """Markdown bullets get hand-wrapped; the continuation belongs to the item.

    Dropping it truncated every long entry mid-sentence, which is how this
    was found — on the rendered page, not in a test.
    """
    release = cl.parse(
        "## v1.0\n### Added\n- A long entry that runs\n  onto a second line\n  and a third.\n"
    )[0]
    assert release.groups[0].items == [
        "A long entry that runs onto a second line and a third."
    ]


def test_a_wrapped_bullet_does_not_swallow_the_next_one():
    release = cl.parse("## v1.0\n### Added\n- one\n  continued\n- two\n")[0]
    assert release.groups[0].items == ["one continued", "two"]


def test_the_shipped_changelog_has_no_truncated_entries():
    """Every entry in the real file should read as a finished sentence."""
    for release in cl.load():
        for group in release.groups:
            for item in group.items:
                assert len(item) > 3
                # A wrapped line that lost its tail usually ends mid-word.
                assert not item.endswith((" a", " the", " was", " which", " and")), (
                    f"suspiciously truncated: {item!r}"
                )
