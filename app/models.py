"""Database models."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class BuylistItem(Base):
    """A specific card printing the user wants to track/buy.

    Price is a placeholder for now (nullable). The tcgplayer_* columns capture
    the product reference so a real price fetch can be wired in later without a
    schema change.
    """

    __tablename__ = "buylist_items"
    __table_args__ = (
        UniqueConstraint("game", "printing_id", name="uq_game_printing"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game: Mapped[str] = mapped_column(String, index=True)

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

    # pricing placeholder
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String, nullable=True)
    tcgplayer_product_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tcgplayer_url: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
