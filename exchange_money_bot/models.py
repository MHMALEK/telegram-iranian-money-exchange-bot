from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    sell_offers: Mapped[list["SellOffer"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class SellOffer(Base):
    """Public sell listing row; used for catalog queries and seller identification."""

    __tablename__ = "sell_offers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    seller_display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    payment_methods: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    """Accepted payment method codes (e.g. cash_in_person, bank); None on legacy rows."""
    listing_direction: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="fx_to_rial",
        default="fx_to_rial",
        index=True,
    )
    """fx_to_rial: sell FX for rial; rial_to_fx: offer rial to buy FX."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    listings_channel_message_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    """Telegram message_id in the public listings channel, if posted."""

    user: Mapped["User"] = relationship(back_populates="sell_offers")
