"""Reading the changelog for the What's new page.

One source of truth: ``CHANGELOG.md`` at the repository root. The page reads
that file rather than keeping a second list in code, because two lists drift
and the one people read is never the one that gets updated.

The parser handles only the markdown this project writes — headings, bullets
and the release line — and deliberately ignores everything else. A general
markdown renderer would be a dependency and an attack surface for a file
only we edit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: Repository root — two levels up from app/services/.
CHANGELOG_PATH = Path(__file__).resolve().parents[2] / "CHANGELOG.md"

_RELEASE = re.compile(r"^##\s+(?P<label>.+?)\s*$")
_GROUP = re.compile(r"^###\s+(?P<label>.+?)\s*$")
_BULLET = re.compile(r"^[-*]\s+(?P<text>.+?)\s*$")


@dataclass
class ReleaseGroup:
    """A run of bullets under one heading, e.g. "Added"."""

    label: str
    items: list[str] = field(default_factory=list)


@dataclass
class Release:
    """One release: its label, and its groups of changes."""

    label: str
    #: "v1.4 — 26 November 2026" split into the two useful halves.
    version: str = ""
    date: str = ""
    groups: list[ReleaseGroup] = field(default_factory=list)

    @property
    def item_count(self) -> int:
        return sum(len(g.items) for g in self.groups)


def _split_label(label: str) -> tuple[str, str]:
    """'v1.4 — 26 November 2026' → ('v1.4', '26 November 2026').

    Accepts an em dash, an en dash, a hyphen or a middot as the separator,
    because all four get typed by a human in a hurry.
    """
    for sep in ("—", "–", "·", " - "):
        if sep in label:
            left, right = label.split(sep, 1)
            return left.strip(), right.strip()
    return label.strip(), ""


def parse(text: str) -> list[Release]:
    """Parse the changelog into releases, newest first as written.

    Text before the first ``##`` is the document's own preamble and is
    skipped — it is for a reader browsing the file, not for the page.
    """
    releases: list[Release] = []
    current: Release | None = None
    group: ReleaseGroup | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if match := _RELEASE.match(stripped):
            version, date = _split_label(match.group("label"))
            current = Release(label=match.group("label"), version=version, date=date)
            releases.append(current)
            group = None
            continue

        if match := _GROUP.match(stripped):
            if current is None:
                continue  # a heading before any release: preamble
            group = ReleaseGroup(label=match.group("label"))
            current.groups.append(group)
            continue

        if match := _BULLET.match(stripped):
            if current is None:
                continue
            if group is None:
                # A bullet with no heading still belongs somewhere.
                group = ReleaseGroup(label="Changed")
                current.groups.append(group)
            group.items.append(match.group("text"))
            continue

        # An indented line that is not a new bullet is a continuation of the
        # one above it — the way any hand-wrapped markdown reads. Dropping
        # these silently truncated every long changelog entry mid-sentence.
        if line[:1].isspace() and group is not None and group.items:
            group.items[-1] = f"{group.items[-1]} {stripped}"
            continue

        # Anything else at the left margin — prose, rules, fences — is not
        # part of a list and is ignored. A changelog is a list.

    return releases


def load(path: Path | None = None) -> list[Release]:
    """Read and parse the changelog. Returns [] when the file is missing.

    An empty list is a legitimate state (a fresh checkout), so the page can
    say so rather than fail.
    """
    file = path or CHANGELOG_PATH
    try:
        return parse(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


__all__ = ["Release", "ReleaseGroup", "parse", "load", "CHANGELOG_PATH"]
