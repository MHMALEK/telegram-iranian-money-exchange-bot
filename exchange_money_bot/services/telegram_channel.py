"""Post sell listings to a Telegram channel and enforce optional chat membership (group and/or channel)."""

from __future__ import annotations

import asyncio
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
    description: Optional[str]


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


def format_listing_html(
    offer: _ListingDisplay,
    *,
    closed: bool = False,
    closed_note_key: str = "listing.closed_note",
) -> str:
    ccy_fa = sell_offers_service.currency_label_fa(offer.currency)
    name = html.escape(offer.seller_display_name.strip(), quote=False)
    ccy_esc = html.escape(ccy_fa, quote=False)
    cur_esc = html.escape(offer.currency, quote=False)
    if offer.telegram_username:
        u = offer.telegram_username.strip().lstrip("@")
        uname = f"@{html.escape(u, quote=False)}"
    else:
        uname = t("listing.no_username")
    parts: list[str] = [
        t("listing.header_html"),
        t(
            "listing.amount_line",
            amount=offer.amount,
            ccy_fa=ccy_esc,
            currency=cur_esc,
        ),
    ]
    desc_raw = offer.description
    if desc_raw and str(desc_raw).strip():
        desc_esc = html.escape(str(desc_raw).strip(), quote=False)
        parts.append(t("listing.description_line", text=desc_esc))
    parts.extend(
        [
            t("listing.seller_line", name=name),
            t("listing.telegram_line", telegram_line=uname),
            "",
            t("listing.tags_template", currency=offer.currency.upper()),
        ]
    )
    body = "\n".join(parts)
    if closed:
        return f"<s>{body}</s>\n\n{t(closed_note_key)}"
    return body


def listing_contact_keyboard(offer: _ListingDisplay) -> InlineKeyboardMarkup:
    ccy_fa = sell_offers_service.currency_label_fa(offer.currency)
    label = t("listing.contact_btn", amount=offer.amount, ccy_fa=ccy_fa)
    max_len = TELEGRAM_INLINE_BUTTON_LABEL_MAX
    if len(label) > max_len:
        label = label[: max_len - 1] + "…"
    contact_btn = InlineKeyboardButton(label, url=_contact_url(offer))
    oid = getattr(offer, "id", None)
    if oid is not None:
        rial_lbl = t("listing.rial_btn")
        if len(rial_lbl) > max_len:
            rial_lbl = rial_lbl[: max_len - 1] + "…"
        return InlineKeyboardMarkup(
            [
                [contact_btn],
                [
                    InlineKeyboardButton(
                        rial_lbl,
                        callback_data=f"rial:{int(oid)}",
                    )
                ],
            ]
        )
    return InlineKeyboardMarkup([[contact_btn]])


async def resolve_listings_channel_open_url(bot: Bot) -> Optional[str]:
    """Invite URL, t.me from @id, or from get_chat (invite_link / username) for numeric channel ids."""
    direct = settings.effective_listings_channel_open_url()
    if direct:
        return direct
    cid = (settings.effective_listings_channel_id() or "").strip()
    if not cid:
        return None
    try:
        chat = await bot.get_chat(chat_id=cid)
        link = getattr(chat, "invite_link", None)
        if link:
            return link
        uname = getattr(chat, "username", None)
        if uname and str(uname).strip():
            return f"https://t.me/{str(uname).strip().lstrip('@')}"
    except TelegramError as e:
        logger.debug("resolve_listings_channel_open_url get_chat failed: %s", e)
    return None


async def resolve_membership_group_open_url(bot: Bot) -> Optional[str]:
    """Invite URL, t.me from @id, or from get_chat for numeric supergroup ids."""
    direct = (settings.telegram_membership_group_invite_url or "").strip()
    if direct:
        return direct
    gid = settings.effective_membership_group_id()
    if not gid:
        return None
    if gid.startswith("@"):
        u = gid[1:].strip()
        if u:
            return f"https://t.me/{u}"
    try:
        chat = await bot.get_chat(chat_id=gid)
        link = getattr(chat, "invite_link", None)
        if link:
            return link
        uname = getattr(chat, "username", None)
        if uname and str(uname).strip():
            return f"https://t.me/{str(uname).strip().lstrip('@')}"
    except TelegramError as e:
        logger.debug("resolve_membership_group_open_url get_chat failed: %s", e)
    return None


async def join_channel_keyboard_async(bot: Bot) -> Optional[InlineKeyboardMarkup]:
    rows: list[list[InlineKeyboardButton]] = []
    if settings.effective_membership_channel_id():
        url = await resolve_listings_channel_open_url(bot)
        if url:
            rows.append([InlineKeyboardButton(t("channel.btn_join"), url=url)])
    if settings.effective_membership_group_id():
        gurl = await resolve_membership_group_open_url(bot)
        if gurl:
            rows.append([InlineKeyboardButton(t("group.btn_join"), url=gurl)])
    if not rows:
        return None
    return InlineKeyboardMarkup(rows)


async def user_is_chat_member(bot: Bot, user_id: int, chat_id: str) -> bool:
    try:
        m = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return m.status in _MEMBER_OK
    except TelegramError as e:
        logger.warning("get_chat_member failed user_id=%s chat=%s: %s", user_id, chat_id, e)
        return False


async def user_passes_membership_gate(bot: Bot, user_id: int) -> bool:
    if not settings.membership_gate_active():
        return True
    gid = settings.effective_membership_group_id()
    cid = settings.effective_membership_channel_id()
    if gid and cid:
        in_group, in_channel = await asyncio.gather(
            user_is_chat_member(bot, user_id, gid),
            user_is_chat_member(bot, user_id, cid),
        )
        return in_group or in_channel
    if gid:
        return await user_is_chat_member(bot, user_id, gid)
    if cid:
        return await user_is_chat_member(bot, user_id, cid)
    return True


async def post_offer_to_listings_channel(bot: Bot, offer: _ListingDisplay) -> Optional[int]:
    cid = settings.effective_listings_channel_id()
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
    closed_note_key: str = "listing.closed_note",
) -> None:
    if bot is None or message_id is None:
        return
    cid = settings.effective_listings_channel_id()
    if not cid:
        return
    text = format_listing_html(offer, closed=True, closed_note_key=closed_note_key)
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
