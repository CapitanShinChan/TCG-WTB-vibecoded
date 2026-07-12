"""SQLite database setup (SQLAlchemy 2.0)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
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


def get_session():
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
