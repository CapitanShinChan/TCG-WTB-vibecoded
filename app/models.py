"""Database models."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class CardList(Base):
    """A named list of cards (e.g. a deck the user wants to buy for).

    Lists are optional groupings: an item with list_id NULL lives in the
    "General" (unlisted) bucket, and the "All" view spans everything.
    """

    __tablename__ = "card_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class BuylistItem(Base):
    """A specific card printing the user wants to track/buy.

    A printing may appear in several lists, each with its own quantity, hence
    the uniqueness is per (game, list_id, printing_id). Note SQLite treats
    NULLs as distinct in a UNIQUE constraint, so the General bucket
    (list_id IS NULL) is additionally protected by a partial unique index
    created in db._post_migrate().
    """

    __tablename__ = "buylist_items"
    __table_args__ = (
        UniqueConstraint(
            "game", "list_id", "printing_id", name="uq_game_list_printing"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game: Mapped[str] = mapped_column(String, index=True)
    list_id: Mapped[int | None] = mapped_column(
        ForeignKey("card_lists.id"), nullable=True, index=True
    )

    card_identifier: Mapped[str] = mapped_column(String)
    card_name: Mapped[str] = mapped_column(String)

    printing_id: Mapped[str] = mapped_column(String)
    printing_label: Mapped[str] = mapped_column(String)
    set_code: Mapped[str | None] = mapped_column(String, nullable=True)
    foiling: Mapped[str | None] = mapped_column(String, nullable=True)
    treatment: Mapped[str | None] = mapped_column(String, nullable=True)
    rarity: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    quantity: Mapped[int] = mapped_column(Integer, default=1)

    # pricing (populated from TCGplayer on refresh)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # current market price
    suggested_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    currency: Mapped[str | None] = mapped_column(String, nullable=True)
    tcgplayer_product_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tcgplayer_url: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
