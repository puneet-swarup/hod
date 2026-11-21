"""The startup guard that shouts when the database schema is behind.

create_all() creates missing tables but never adds missing columns, so a
release with a migration deployed without `alembic upgrade head` starts
healthy and then fails on the first page that reads a new column. These
tests pin the warning, and — just as important — that it stays quiet on a
fresh database and on a database that is already current.
"""

from sqlalchemy import text


def _set_revision(revision: str) -> None:
    from app.database import engine as app_engine

    with app_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:rev)"), {"rev": revision}
        )


def _clear_revision() -> None:
    from app.database import engine as app_engine

    with app_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


def test_guard_is_quiet_without_an_alembic_version_table():
    """A fresh create_all database (tests, first run) has nothing to compare."""
    from app.main import warn_if_schema_is_behind

    _clear_revision()
    assert warn_if_schema_is_behind() is None


def test_guard_is_quiet_when_the_database_is_current():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.main import warn_if_schema_is_behind

    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    _set_revision(head)
    try:
        assert warn_if_schema_is_behind() is None
    finally:
        _clear_revision()


def test_guard_warns_when_the_database_is_behind():
    from app.main import warn_if_schema_is_behind

    _set_revision("e3c4d5f6a7b8")  # the revision before the B2B release
    try:
        message = warn_if_schema_is_behind()
        assert message is not None
        assert "e3c4d5f6a7b8" in message
        assert "alembic upgrade head" in message
        assert "no such column" in message
    finally:
        _clear_revision()
