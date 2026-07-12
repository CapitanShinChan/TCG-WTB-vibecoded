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

    Base.metadata.create_all(ENGINE)
    _migrate()


# Columns added after the initial release. SQLite create_all won't add columns
# to an existing table, so add any that are missing. (name -> SQL type)
_ADDED_COLUMNS = {
    "buylist_items": {
        "suggested_price": "FLOAT",
        "price_sample_size": "INTEGER",
        "price_updated_at": "DATETIME",
    },
}


def _migrate() -> None:
    insp = inspect(ENGINE)
    tables = set(insp.get_table_names())
    with ENGINE.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            if table not in tables:
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, sql_type in cols.items():
                if name not in existing:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
                    )


def get_session():
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
