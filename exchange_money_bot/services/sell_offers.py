from dataclasses import dataclass
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exchange_money_bot.i18n import t
from exchange_money_bot.models import SellOffer

ALLOWED_CURRENCIES = frozenset({"EUR", "USD"})
MAX_OFFER_DESCRIPTION_LEN = 200

PAYMENT_CASH_IN_PERSON = "cash_in_person"
PAYMENT_BANK = "bank"
PAYMENT_CRYPTO = "crypto"
PAYMENT_OTHER = "other"

PAYMENT_METHOD_CODES_ORDER: tuple[str, ...] = (
    PAYMENT_CASH_IN_PERSON,
    PAYMENT_BANK,
    PAYMENT_CRYPTO,
    PAYMENT_OTHER,
)
ALLOWED_PAYMENT_METHODS = frozenset(PAYMENT_METHOD_CODES_ORDER)


def normalize_offer_description(raw: Optional[str]) -> Optional[str]:
    """Strip whitespace; empty becomes None; raises ValueError if over max length."""
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if len(s) > MAX_OFFER_DESCRIPTION_LEN:
        raise ValueError("Description too long")
    return s


def normalize_payment_methods(raw: Optional[Sequence[str]]) -> list[str]:
    """Deduplicate, keep canonical order; raises ValueError if empty or no valid codes."""
    if raw is None:
        raise ValueError("Payment methods required")
    chosen = [c for c in PAYMENT_METHOD_CODES_ORDER if c in raw]
    if not chosen:
        raise ValueError("Invalid or empty payment methods")
    return chosen


def payment_method_label_fa(code: str) -> str:
    return t(f"payment.{code}", default=code)


def format_payment_methods_summary_fa(codes: Optional[Sequence[str]]) -> str:
    if not codes:
        return t("payment.summary_unspecified")
    ordered = [c for c in PAYMENT_METHOD_CODES_ORDER if c in codes]
    if not ordered:
        return t("payment.summary_unspecified")
    return "، ".join(payment_method_label_fa(c) for c in ordered)


@dataclass
class DeletedSellOfferSnapshot:
    """Row fields needed after an offer row is removed (e.g. channel strikethrough)."""

    amount: int
    currency: str
    seller_display_name: str
    telegram_username: Optional[str]
    telegram_id: int
    listings_channel_message_id: Optional[int]
    description: Optional[str] = None
    payment_methods: Optional[list[str]] = None


def currency_label_fa(code: str) -> str:
    return t(f"currency.{code}", default=code)


async def count_public_sell_offers(
    session: AsyncSession,
    *,
    exclude_telegram_id: Optional[int] = None,
    currency: Optional[str] = None,
) -> int:
    stmt = select(func.count()).select_from(SellOffer)
    if exclude_telegram_id is not None:
        stmt = stmt.where(SellOffer.telegram_id != exclude_telegram_id)
    if currency is not None:
        if currency not in ALLOWED_CURRENCIES:
            raise ValueError(f"Invalid currency: {currency}")
        stmt = stmt.where(SellOffer.currency == currency)
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def count_offers_by_telegram_and_currency(
    session: AsyncSession,
    telegram_id: int,
    currency: str,
) -> int:
    if currency not in ALLOWED_CURRENCIES:
        raise ValueError(f"Invalid currency: {currency}")
    stmt = select(func.count()).select_from(SellOffer).where(
        SellOffer.telegram_id == telegram_id,
        SellOffer.currency == currency,
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def list_public_sell_offers(
    session: AsyncSession,
    *,
    exclude_telegram_id: Optional[int] = None,
    currency: Optional[str] = None,
    limit: int = 5,
    offset: int = 0,
) -> list[SellOffer]:
    stmt = select(SellOffer).order_by(SellOffer.created_at.desc())
    if exclude_telegram_id is not None:
        stmt = stmt.where(SellOffer.telegram_id != exclude_telegram_id)
    if currency is not None:
        if currency not in ALLOWED_CURRENCIES:
            raise ValueError(f"Invalid currency: {currency}")
        stmt = stmt.where(SellOffer.currency == currency)
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_offers_for_user(session: AsyncSession, user_id: int) -> list[SellOffer]:
    result = await session.execute(
        select(SellOffer)
        .where(SellOffer.user_id == user_id)
        .order_by(SellOffer.created_at.desc())
    )
    return list(result.scalars().all())


async def get_offer_by_id(session: AsyncSession, offer_id: int) -> Optional[SellOffer]:
    result = await session.execute(select(SellOffer).where(SellOffer.id == offer_id))
    return result.scalar_one_or_none()


async def delete_offer_owned(
    session: AsyncSession, offer_id: int, user_id: int
) -> Optional[DeletedSellOfferSnapshot]:
    result = await session.execute(
        select(SellOffer).where(SellOffer.id == offer_id, SellOffer.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    snap = DeletedSellOfferSnapshot(
        amount=row.amount,
        currency=row.currency,
        seller_display_name=row.seller_display_name,
        telegram_username=row.telegram_username,
        telegram_id=row.telegram_id,
        listings_channel_message_id=row.listings_channel_message_id,
        description=getattr(row, "description", None),
        payment_methods=getattr(row, "payment_methods", None),
    )
    await session.delete(row)
    await session.commit()
    return snap


async def set_listings_channel_message_id(
    session: AsyncSession, offer_id: int, message_id: int
) -> None:
    result = await session.execute(select(SellOffer).where(SellOffer.id == offer_id))
    row = result.scalar_one_or_none()
    if row is None:
        return
    row.listings_channel_message_id = message_id
    await session.commit()


async def create_sell_offer(
    session: AsyncSession,
    *,
    user_id: int,
    telegram_id: int,
    telegram_username: Optional[str],
    seller_display_name: str,
    amount: int,
    currency: str,
    description: Optional[str] = None,
    payment_methods: Optional[Sequence[str]] = None,
) -> SellOffer:
    if currency not in ALLOWED_CURRENCIES:
        raise ValueError(f"Invalid currency: {currency}")
    if amount <= 0:
        raise ValueError("Amount must be positive")
    desc = normalize_offer_description(description)
    methods = normalize_payment_methods(payment_methods)
    offer = SellOffer(
        user_id=user_id,
        telegram_id=telegram_id,
        telegram_username=telegram_username,
        seller_display_name=seller_display_name,
        amount=amount,
        currency=currency,
        description=desc,
        payment_methods=methods,
    )
    session.add(offer)
    await session.commit()
    await session.refresh(offer)
    return offer
