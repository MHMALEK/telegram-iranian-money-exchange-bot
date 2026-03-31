"""Post sell listings to a Telegram channel and enforce optional channel membership."""

from __future__ import annotations

import html
import logging
from typing import Optional, Protocol, Sequence

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError

from exchange_money_bot.config import settings
from exchange_money_bot.constants import TELEGRAM_INLINE_BUTTON_LABEL_MAX
from exchange_money_bot.i18n import t
from exchange_money_bot.services import sell_offers as sell_offers_service

logger = logging.getLogger(__name__)


class _ListingDisplay(Protocol):
    amount: int
    currency: str
    seller_display_name: str
    telegram_username: Optional[str]
    telegram_id: int


_MEMBER_OK = frozenset(
    {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
        ChatMemberStatus.RESTRICTED,
    }
)


def _contact_url(offer: _ListingDisplay) -> str:
    if offer.telegram_username:
        u = offer.telegram_username.strip().lstrip("@")
        if u:
            return f"https://t.me/{u}"
    return f"tg://user?id={offer.telegram_id}"


def format_listing_html(offer: _ListingDisplay, *, closed: bool = False) -> str:
    ccy_fa = sell_offers_service.currency_label_fa(offer.currency)
    name = html.escape(offer.seller_display_name.strip(), quote=False)
    ccy_esc = html.escape(ccy_fa, quote=False)
    cur_esc = html.escape(offer.currency, quote=False)
    if offer.telegram_username:
        u = offer.telegram_username.strip().lstrip("@")
        uname = f"@{html.escape(u, quote=False)}"
    else:
        uname = t("listing.no_username")
    body = "\n".join(
        [
            t("listing.header_html"),
            t(
                "listing.amount_line",
                amount=offer.amount,
                ccy_fa=ccy_esc,
                currency=cur_esc,
            ),
            t("listing.seller_line", name=name),
            t("listing.telegram_line", telegram_line=uname),
            "",
            t("listing.tags_template", currency=offer.currency.upper()),
        ]
    )
    if closed:
        return f"<s>{body}</s>\n\n{t('listing.closed_note')}"
    return body


def listing_contact_keyboard(offer: _ListingDisplay) -> InlineKeyboardMarkup:
    ccy_fa = sell_offers_service.currency_label_fa(offer.currency)
    label = t("listing.contact_btn", amount=offer.amount, ccy_fa=ccy_fa)
    max_len = TELEGRAM_INLINE_BUTTON_LABEL_MAX
    if len(label) > max_len:
        label = label[: max_len - 1] + "…"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, url=_contact_url(offer))]])


def join_channel_keyboard() -> Optional[InlineKeyboardMarkup]:
    url = settings.effective_listings_channel_open_url()
    if not url:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("channel.btn_join"), url=url)]])


async def user_is_channel_member(
    bot: Bot, user_id: int, channel_chat_id: str
) -> bool:
    try:
        m = await bot.get_chat_member(chat_id=channel_chat_id, user_id=user_id)
        return m.status in _MEMBER_OK
    except TelegramError as e:
        logger.warning("get_chat_member failed user_id=%s chat=%s: %s", user_id, channel_chat_id, e)
        return False


async def user_passes_membership_gate(bot: Bot, user_id: int) -> bool:
    if not settings.membership_gate_active():
        return True
    cid = settings.effective_membership_channel_id()
    assert cid is not None
    return await user_is_channel_member(bot, user_id, cid)


async def post_offer_to_listings_channel(bot: Bot, offer: _ListingDisplay) -> Optional[int]:
    cid = settings.telegram_listings_channel_id
    if not cid:
        return None
    text = format_listing_html(offer, closed=False)
    try:
        msg = await bot.send_message(
            chat_id=cid,
            text=text,
            parse_mode="HTML",
            reply_markup=listing_contact_keyboard(offer),
        )
        return int(msg.message_id)
    except TelegramError:
        oid = getattr(offer, "id", "?")
        logger.exception("Failed to post listing offer_id=%s to channel", oid)
        return None


async def mark_listing_closed_on_channel(
    bot: Optional[Bot],
    *,
    message_id: Optional[int],
    offer: _ListingDisplay,
) -> None:
    if bot is None or message_id is None:
        return
    cid = settings.telegram_listings_channel_id
    if not cid:
        return
    text = format_listing_html(offer, closed=True)
    try:
        await bot.edit_message_text(
            chat_id=cid,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=None,
        )
    except TelegramError:
        logger.warning(
            "Could not strikethrough listing message_id=%s (offer may be old or deleted)",
            message_id,
        )


async def close_listings_for_offers(
    bot: Optional[Bot],
    offers: Sequence[_ListingDisplay],
) -> None:
    for o in offers:
        mid = getattr(o, "listings_channel_message_id", None)
        if mid is not None:
            await mark_listing_closed_on_channel(bot, message_id=mid, offer=o)
