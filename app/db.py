"""SQLite database setup (SQLAlchemy 2.0)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_PATH = Path(__file__).resolve().parent.parent / "inventory.db"
ENGINE = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, future=True)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    # import models so they register on Base before create_all
    from . import models  # noqa: F401

    _pre_migrate()   # step aside outdated tables so create_all can rebuild them
    Base.metadata.create_all(ENGINE)
    _post_migrate()  # copy preserved rows back, add columns / indexes


# Columns added after the initial release. SQLite create_all won't add columns
# to an existing table, so add any that are missing. (name -> SQL type)
_ADDED_COLUMNS = {
    "buylist_items": {
        "suggested_price": "FLOAT",
        "price_sample_size": "INTEGER",
        "price_updated_at": "DATETIME",
    },
}


_LEGACY_SUFFIX = "_legacy"


def _pre_migrate() -> None:
    """Rename tables whose schema can't be altered in place (SQLite can't change
    a UNIQUE constraint), so create_all() rebuilds them with the current schema.
    _post_migrate() then copies the preserved rows back."""
    insp = inspect(ENGINE)
    tables = set(insp.get_table_names())
    if "buylist_items" not in tables:
        return
    cols = {c["name"] for c in insp.get_columns("buylist_items")}
    if "list_id" in cols:
        return  # already migrated
    legacy = f"buylist_items{_LEGACY_SUFFIX}"
    # index names are global in SQLite and follow the renamed table, so drop the
    # explicitly-created ones or create_all() will collide on the rebuilt table
    stale_indexes = [
        ix["name"] for ix in insp.get_indexes("buylist_items") if ix.get("name")
    ]
    with ENGINE.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {legacy}"))
        for name in stale_indexes:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        conn.execute(text(f"ALTER TABLE buylist_items RENAME TO {legacy}"))


def _post_migrate() -> None:
    insp = inspect(ENGINE)
    tables = set(insp.get_table_names())

    with ENGINE.begin() as conn:
        # 1. columns added to existing tables after the initial release
        for table, cols in _ADDED_COLUMNS.items():
            if table not in tables:
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, sql_type in cols.items():
                if name not in existing:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
                    )

        # 2. copy rows from a rebuilt table, then drop the legacy copy
        legacy = f"buylist_items{_LEGACY_SUFFIX}"
        if legacy in tables:
            old_cols = {c["name"] for c in insp.get_columns(legacy)}
            new_cols = {c["name"] for c in insp.get_columns("buylist_items")}
            shared = sorted(old_cols & new_cols)
            col_list = ", ".join(shared)
            conn.execute(
                text(
                    f"INSERT INTO buylist_items ({col_list}) "
                    f"SELECT {col_list} FROM {legacy}"
                )
            )
            conn.execute(text(f"DROP TABLE {legacy}"))

        # 3. SQLite treats NULLs as distinct in a UNIQUE constraint, so the
        #    General bucket (list_id IS NULL) needs a partial unique index.
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_general_game_printing "
                "ON buylist_items (game, printing_id) WHERE list_id IS NULL"
            )
        )


def get_session():
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
