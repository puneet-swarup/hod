"""The deployment script must not go stale.

The deploy script is the one piece of code that runs when everything else is
in a known-good state, so a check missing from it is invisible until the day
it matters. These tests read the script and assert the checks it is supposed
to have are still there.

They are deliberately shallow: a test that read shell semantics would be a
test of bash. What is checked is presence and intent, which is enough to stop
a check being deleted during a refactor.

**When you add a check to the deploy script, add it to `REQUIRED_CHECKS` and
to `REQUIRED_FLAGS`.** That list is the contract.
"""

import pathlib
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "deploy.sh"

#: Every check the script is required to make, and the phrase that proves it.
REQUIRED_CHECKS = {
    "is this the right machine": "app folder found",
    "settings file present": "settings file found",
    "python environment present": "python environment found",
    "backup before anything is touched": "Backing up the database",
    "migrations run": "alembic",
    "service restarted": "Restarting the app",
    "health endpoint checked": "health endpoint answers",
    "schema matches the code": "database schema matches the code",
    # Added 26 Nov: the release must describe itself.
    "release has a changelog entry": "Checking the release is complete",
    "changelog is not behind the code": "CHANGELOG.md is behind the code",
}

#: Flags the script must keep offering.
REQUIRED_FLAGS = ["--status", "--rollback", "--dry-run", "--yes", "--test"]


def _script() -> str:
    assert SCRIPT.exists(), f"deploy script missing at {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def test_the_script_exists_and_is_executable():
    assert SCRIPT.exists()
    assert SCRIPT.stat().st_mode & 0o111, "deploy.sh must be executable"


def test_the_script_parses():
    """A syntax error in this file is a deploy that dies halfway."""
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("name", "phrase"), sorted(REQUIRED_CHECKS.items()))
def test_a_required_check_is_still_there(name, phrase):
    assert phrase in _script(), f"the deploy script no longer checks: {name}"


@pytest.mark.parametrize("flag", REQUIRED_FLAGS)
def test_a_required_flag_is_still_offered(flag):
    assert flag in _script(), f"the deploy script no longer accepts {flag}"


def test_the_release_check_reads_the_incoming_commit():
    """It must check the code being deployed, not the copy already on disk.

    Reading the working tree would pass a release that was never pushed with
    a changelog entry — the exact mistake this check exists to catch.
    """
    script = _script()
    assert 'git show "$REMOTE_SHA:CHANGELOG.md"' in script


def test_the_release_check_stops_rather_than_warns():
    """A missing changelog entry is a stop: the release is incomplete."""
    script = _script()
    block = script.split("Checking the release is complete")[1][:2000]
    assert "die " in block, "the release check should stop the deploy"
    assert "no entry in CHANGELOG.md" in block


def test_the_summary_joins_wrapped_lines():
    """A changelog entry is hand-wrapped; half a sentence on the terminal is
    worse than none, and this exact bug shipped once already."""
    script = _script()
    summary = script.split("release_summary()")[1].split("\n}")[0]
    assert "flush" in summary, "the summary should accumulate continuation lines"
