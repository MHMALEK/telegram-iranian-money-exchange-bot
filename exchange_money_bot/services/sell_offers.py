from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exchange_money_bot.models import SellOffer

ALLOWED_CURRENCIES = frozenset({"EUR", "USD", "USDT"})


def currency_label_fa(code: str) -> str:
    return {"EUR": "یورو", "USD": "دلار", "USDT": "تتر"}.get(code, code)


async def list_offers_for_user(session: AsyncSession, user_id: int) -> list[SellOffer]:
    result = await session.execute(
        select(SellOffer)
        .where(SellOffer.user_id == user_id)
        .order_by(SellOffer.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_offer_owned(session: AsyncSession, offer_id: int, user_id: int) -> bool:
    result = await session.execute(
        select(SellOffer).where(SellOffer.id == offer_id, SellOffer.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def create_sell_offer(
    session: AsyncSession,
    *,
    user_id: int,
    telegram_id: int,
    telegram_username: Optional[str],
    seller_display_name: str,
    amount: int,
    currency: str,
) -> SellOffer:
    if currency not in ALLOWED_CURRENCIES:
        raise ValueError(f"Invalid currency: {currency}")
    if amount <= 0:
        raise ValueError("Amount must be positive")
    offer = SellOffer(
        user_id=user_id,
        telegram_id=telegram_id,
        telegram_username=telegram_username,
        seller_display_name=seller_display_name,
        amount=amount,
        currency=currency,
    )
    session.add(offer)
    await session.commit()
    await session.refresh(offer)
    return offer
