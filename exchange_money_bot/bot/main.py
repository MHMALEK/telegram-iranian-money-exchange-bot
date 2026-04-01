import html
import logging
import re
from typing import Optional

import httpx
from telegram import Bot, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from exchange_money_bot.bot.keyboards import (
    MENU_MAIN_CALLBACK,
    main_menu_keyboard,
    with_back_to_main,
)
from exchange_money_bot.bot.sell_flow import build_sell_conversation_handler
from exchange_money_bot.config import settings
from exchange_money_bot.database import async_session_factory, init_db
from exchange_money_bot.i18n import t
from exchange_money_bot.services import irr_fiat_rates
from exchange_money_bot.services import sell_offers as sell_offers_service
from exchange_money_bot.services import telegram_channel as telegram_channel_service
from exchange_money_bot.services import users as user_service
from exchange_money_bot.services.sell_offers import DeletedSellOfferSnapshot

logger = logging.getLogger(__name__)


async def _edit_or_reply(
    message,
    text: str,
    *,
    reply_markup=None,
    parse_mode: Optional[str] = None,
    disable_web_page_preview: bool = False,
) -> None:
    """Edit the message that carried the callback; fall back to a new reply if edit fails."""
    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
    except Exception:
        await message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )


_BUY_CCY = r"(EUR|USD)"
BUY_FLOW_CALLBACK_PATTERN = rf"^buy:(choose|ccy:{_BUY_CCY}|cat:{_BUY_CCY}:\d+)$"


async def _listings_channel_cta_keyboard_async(bot: Bot) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    open_url = await telegram_channel_service.resolve_listings_channel_open_url(bot)
    if open_url:
        rows.append(
            [
                InlineKeyboardButton(
                    t("channel.btn_open"),
                    url=open_url,
                )
            ]
        )
    return with_back_to_main(InlineKeyboardMarkup(rows))


async def _listings_channel_message_body_async(bot: Bot, *, for_rial: bool) -> str:
    base = t("listings.cta_rial_html") if for_rial else t("listings.cta_html")
    open_url = await telegram_channel_service.resolve_listings_channel_open_url(bot)
    if open_url:
        url_esc = html.escape(open_url, quote=True)
        label_esc = html.escape(t("listings.channel_link_label"), quote=False)
        return f'{base}\n\n<a href="{url_esc}">{label_esc}</a>'
    if settings.effective_listings_channel_id():
        return f"{base}\n\n{t('listings.cta_no_direct_link_html')}"
    return base


async def execute_buy_flow_callback(query: CallbackQuery, bot: Bot) -> None:
    """Legacy buy:* callbacks now only point users to the public listings channel."""
    if query.data is None or query.message is None or query.from_user is None:
        await query.answer()
        return
    await query.answer()
    tid = query.from_user.id
    async with async_session_factory() as session:
        registered = await user_service.get_user_by_telegram(session, tid)
    if registered is None:
        await _edit_or_reply(
            query.message,
            t("error.register_first"),
            reply_markup=with_back_to_main(InlineKeyboardMarkup([])),
        )
        return
    if not await telegram_channel_service.user_passes_membership_gate(bot, tid):
        join_kb = (
            await telegram_channel_service.join_channel_keyboard_async(bot)
            or InlineKeyboardMarkup([])
        )
        await _edit_or_reply(
            query.message,
            t("membership.required_html"),
            reply_markup=with_back_to_main(join_kb),
            parse_mode="HTML",
        )
        return
    await _edit_or_reply(
        query.message,
        await _listings_channel_message_body_async(bot, for_rial=False),
        reply_markup=await _listings_channel_cta_keyboard_async(bot),
        parse_mode="HTML",
    )


async def buy_flow_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await execute_buy_flow_callback(query, context.bot)


async def listing_rial_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Channel listing: approximate IRR for the offer amount (alert only, no chat state)."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    m = re.fullmatch(r"rial:(\d+)", query.data)
    if not m:
        return
    offer_id = int(m.group(1))
    async with async_session_factory() as session:
        offer = await sell_offers_service.get_offer_by_id(session, offer_id)
    if offer is None:
        await query.answer(t("rates.listing_rial_gone"), show_alert=True)
        return
    if getattr(offer, "listing_direction", None) == sell_offers_service.LISTING_RIAL_TO_FX:
        await query.answer(t("rates.listing_rial_not_applicable"), show_alert=True)
        return
    try:
        usd, eur, _ts = await irr_fiat_rates.get_usd_eur_rial_snapshot(
            usd_json_url=settings.irr_usd_json_url or irr_fiat_rates.DEFAULT_USD_JSON_URL,
            eur_json_url=settings.irr_eur_json_url or irr_fiat_rates.DEFAULT_EUR_JSON_URL,
            ttl_seconds=settings.irr_rates_ttl_seconds,
        )
    except Exception:
        logger.exception("listing rial snapshot failed")
        usd, eur = None, None
    total = irr_fiat_rates.rial_equivalent(
        offer.amount,
        offer.currency,
        usd_rial=usd if isinstance(usd, int) else None,
        eur_rial=eur if isinstance(eur, int) else None,
    )
    if total is None:
        await query.answer(t("rates.listing_rial_no_rate"), show_alert=True)
        return
    rate = usd if offer.currency == "USD" else eur
    ccy_fa = sell_offers_service.currency_label_fa(offer.currency)
    msg = t(
        "rates.listing_rial_alert",
        amount=offer.amount,
        ccy_fa=ccy_fa,
        code=offer.currency,
        rate=rate,
        total=total,
    )
    if len(msg) > 640:
        msg = msg[:637] + "…"
    await query.answer(msg, show_alert=True)


async def rates_spot_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Live USD/EUR per-unit rial banner (TGJU JSON via margani/pricedb)."""
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return
    await query.answer()
    tid = query.from_user.id
    async with async_session_factory() as session:
        reg = await user_service.get_user_by_telegram(session, tid)
    if reg is None:
        await _edit_or_reply(
            query.message,
            t("error.register_first"),
            reply_markup=with_back_to_main(InlineKeyboardMarkup([])),
        )
        return
    if not await telegram_channel_service.user_passes_membership_gate(context.bot, tid):
        join_kb = (
            await telegram_channel_service.join_channel_keyboard_async(context.bot)
            or InlineKeyboardMarkup([])
        )
        await _edit_or_reply(
            query.message,
            t("membership.required_html"),
            reply_markup=with_back_to_main(join_kb),
            parse_mode="HTML",
        )
        return
    try:
        usd, eur, ts = await irr_fiat_rates.get_usd_eur_rial_snapshot(
            usd_json_url=settings.irr_usd_json_url or irr_fiat_rates.DEFAULT_USD_JSON_URL,
            eur_json_url=settings.irr_eur_json_url or irr_fiat_rates.DEFAULT_EUR_JSON_URL,
            ttl_seconds=settings.irr_rates_ttl_seconds,
        )
    except Exception:
        logger.exception("rates spot snapshot failed")
        usd, eur, ts = None, None, None
    banner = irr_fiat_rates.format_buyer_rates_banner_html(usd, eur, ts)
    if not banner:
        await _edit_or_reply(
            query.message,
            t("rates.unavailable_html"),
            parse_mode="HTML",
            reply_markup=with_back_to_main(InlineKeyboardMarkup([])),
            disable_web_page_preview=True,
        )
        return
    await _edit_or_reply(
        query.message,
        banner + "\n\n" + t("rates.spot_footer_html"),
        parse_mode="HTML",
        reply_markup=with_back_to_main(InlineKeyboardMarkup([])),
        disable_web_page_preview=True,
    )


def consent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("consent.btn_yes"),
                    callback_data="consent:yes",
                ),
            ],
            [
                InlineKeyboardButton(
                    t("consent.btn_no"),
                    callback_data="consent:no",
                ),
            ],
        ]
    )


def delete_confirm_keyboard() -> InlineKeyboardMarkup:
    return with_back_to_main(
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        t("account.delete_btn_yes"),
                        callback_data="account:delete_yes",
                    ),
                    InlineKeyboardButton(
                        t("account.delete_btn_cancel"),
                        callback_data="account:delete_no",
                    ),
                ],
            ]
        )
    )


async def apply_home_screen(query, bot: Bot) -> None:
    """Same outcome as /start: main menu for registered users or consent screen for guests."""
    if query.message is None or query.from_user is None:
        return
    tid = query.from_user.id
    if not await telegram_channel_service.user_passes_membership_gate(bot, tid):
        join_kb = (
            await telegram_channel_service.join_channel_keyboard_async(bot)
            or InlineKeyboardMarkup([])
        )
        await _edit_or_reply(
            query.message,
            t("membership.required_html"),
            reply_markup=with_back_to_main(join_kb),
            parse_mode="HTML",
        )
        return
    async with async_session_factory() as session:
        db_user = await user_service.get_user_by_telegram(session, tid)
    if db_user is not None:
        await _edit_or_reply(
            query.message,
            t("home.registered"),
            reply_markup=main_menu_keyboard(),
        )
    else:
        await _edit_or_reply(
            query.message,
            t("consent.body_html"),
            reply_markup=consent_keyboard(),
            parse_mode="HTML",
        )


async def menu_main_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return
    await query.answer()
    await apply_home_screen(query, context.bot)


async def delete_user_data(telegram_id: int, bot: Optional[Bot] = None) -> bool:
    async with async_session_factory() as session:
        user = await user_service.get_user_by_telegram(session, telegram_id)
        if user is None:
            return False
        offers = await sell_offers_service.list_offers_for_user(session, user.id)
        snapshots = [
            DeletedSellOfferSnapshot(
                amount=o.amount,
                currency=o.currency,
                seller_display_name=o.seller_display_name,
                telegram_username=o.telegram_username,
                telegram_id=o.telegram_id,
                listings_channel_message_id=o.listings_channel_message_id,
                description=o.description,
                payment_methods=o.payment_methods,
                listing_direction=o.listing_direction,
            )
            for o in offers
        ]
    await telegram_channel_service.close_listings_for_offers(bot, snapshots)
    async with async_session_factory() as session:
        return await user_service.delete_user_by_telegram(session, telegram_id)


async def build_my_offers_ui(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with async_session_factory() as session:
        offers = await sell_offers_service.list_offers_for_user(session, user_id)
    lines = [t("offers.title_html"), ""]
    rows: list[list[InlineKeyboardButton]] = []
    if not offers:
        lines.append(t("offers.empty"))
    else:
        for i, o in enumerate(offers, start=1):
            ld = getattr(o, "listing_direction", None) or sell_offers_service.DEFAULT_LISTING_DIRECTION
            kind_prefix = (
                t("offers.kind_rial_to_fx")
                if ld == sell_offers_service.LISTING_RIAL_TO_FX
                else t("offers.kind_fx_to_rial")
            )
            ccy = sell_offers_service.currency_label_fa(o.currency)
            dt = (
                o.created_at.strftime("%Y-%m-%d %H:%M")
                if o.created_at is not None
                else t("sell.display_fallback")
            )
            desc_suffix = ""
            if o.description and str(o.description).strip():
                snippet = html.escape(str(o.description).strip()[:72], quote=False)
                if len(str(o.description).strip()) > 72:
                    snippet += "…"
                desc_suffix = t("offers.desc_line_html", snippet=snippet)
            pay_suffix = ""
            pm = o.payment_methods
            if pm:
                ordered = [
                    c for c in sell_offers_service.PAYMENT_METHOD_CODES_ORDER if c in pm
                ]
                if ordered:
                    pay_suffix = t(
                        "offers.payment_line_html",
                        methods=html.escape(
                            sell_offers_service.format_payment_methods_summary_fa(pm),
                            quote=False,
                        ),
                    )
            line_key = (
                "offers.line_html_rial_to_fx"
                if ld == sell_offers_service.LISTING_RIAL_TO_FX
                else "offers.line_html_fx_to_rial"
            )
            lines.append(
                t(
                    line_key,
                    i=i,
                    kind_prefix=kind_prefix,
                    amount=o.amount,
                    ccy=ccy,
                    dt=dt,
                    desc_suffix=desc_suffix,
                    pay_suffix=pay_suffix,
                )
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        t("offers.btn_remove_i", i=i),
                        callback_data=f"offer:del:{o.id}",
                    ),
                    InlineKeyboardButton(
                        t("offers.btn_sold_i", i=i),
                        callback_data=f"offer:sold:{o.id}",
                    ),
                ]
            )
    if offers:
        lines.extend(["", t("offers.relist_hint_html")])
    return "\n".join(lines), with_back_to_main(InlineKeyboardMarkup(rows))


async def account_manage_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return
    await query.answer()
    tid = query.from_user.id
    if not await telegram_channel_service.user_passes_membership_gate(context.bot, tid):
        join_kb = (
            await telegram_channel_service.join_channel_keyboard_async(context.bot)
            or InlineKeyboardMarkup([])
        )
        await _edit_or_reply(
            query.message,
            t("membership.required_html"),
            reply_markup=with_back_to_main(join_kb),
            parse_mode="HTML",
        )
        return
    async with async_session_factory() as session:
        db_user = await user_service.get_user_by_telegram(session, tid)
    if db_user is None:
        await _edit_or_reply(
            query.message,
            t("error.register_first_short"),
            reply_markup=with_back_to_main(InlineKeyboardMarkup([])),
        )
        return
    text, keyboard = await build_my_offers_ui(db_user.id)
    await _edit_or_reply(
        query.message,
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def offer_action_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Close an offer: remove from DB and strikethrough channel post (delete vs sold wording)."""
    query = update.callback_query
    if (
        query is None
        or query.message is None
        or query.data is None
        or query.from_user is None
    ):
        return
    m = re.fullmatch(r"offer:(del|sold):(\d+)", query.data)
    if not m:
        return
    action = m.group(1)
    offer_id = int(m.group(2))
    tid = query.from_user.id
    if not await telegram_channel_service.user_passes_membership_gate(context.bot, tid):
        await query.answer(t("error.join_channel_first"), show_alert=True)
        return
    async with async_session_factory() as session:
        db_user = await user_service.get_user_by_telegram(session, tid)
        if db_user is None:
            await query.answer(t("error.register_alert"), show_alert=True)
            return
        snap = await sell_offers_service.delete_offer_owned(
            session, offer_id, db_user.id
        )
        if snap is None:
            await query.answer(t("error.offer_not_yours"), show_alert=True)
            return
    note_key = (
        "listing.sold_note" if action == "sold" else "listing.closed_note"
    )
    await telegram_channel_service.mark_listing_closed_on_channel(
        context.bot,
        message_id=snap.listings_channel_message_id,
        offer=snap,
        closed_note_key=note_key,
    )
    await query.answer(
        t("success.offer_sold" if action == "sold" else "success.offer_deleted")
    )
    text, keyboard = await build_my_offers_ui(db_user.id)
    await _edit_or_reply(
        query.message,
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def notify_api_after_upsert(telegram_id: int) -> None:
    if not settings.api_base_url:
        return
    url = f"{settings.api_base_url.rstrip('/')}/users/by-telegram/{telegram_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.get(url)
    except Exception:
        logger.exception("Optional API ping after /start failed")


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    u = update.effective_user
    if not await telegram_channel_service.user_passes_membership_gate(context.bot, u.id):
        join_kb = (
            await telegram_channel_service.join_channel_keyboard_async(context.bot)
            or InlineKeyboardMarkup([])
        )
        await update.message.reply_text(
            t("membership.required_html"),
            reply_markup=with_back_to_main(join_kb),
            parse_mode="HTML",
        )
        return
    async with async_session_factory() as session:
        existing = await user_service.get_user_by_telegram(session, u.id)

    if existing is not None:
        await update.message.reply_text(
            t("home.registered"),
            reply_markup=main_menu_keyboard(),
        )
        return

    await update.message.reply_text(
        t("consent.body_html"),
        reply_markup=consent_keyboard(),
        parse_mode="HTML",
    )


async def consent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if query.from_user is None:
        return

    await query.answer()

    if query.data == "consent:no":
        await _edit_or_reply(
            query.message,
            t("consent.declined"),
            reply_markup=with_back_to_main(InlineKeyboardMarkup([])),
        )
        return

    if query.data != "consent:yes":
        return

    u = query.from_user
    if not await telegram_channel_service.user_passes_membership_gate(
        context.bot, u.id
    ):
        join_kb = (
            await telegram_channel_service.join_channel_keyboard_async(context.bot)
            or InlineKeyboardMarkup([])
        )
        await _edit_or_reply(
            query.message,
            t("membership.required_html"),
            reply_markup=with_back_to_main(join_kb),
            parse_mode="HTML",
        )
        return

    async with async_session_factory() as session:
        await user_service.upsert_user(
            session,
            telegram_id=u.id,
            username=u.username,
            first_name=u.first_name,
        )
    await notify_api_after_upsert(u.id)
    await _edit_or_reply(
        query.message, t("signup.success"), reply_markup=main_menu_keyboard()
    )


async def start_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Listings channel CTA (start:rial from menu; start:2 optional for old keyboards)."""
    query = update.callback_query
    if query is None or query.data is None or query.message is None or query.from_user is None:
        return
    await query.answer()
    tid = query.from_user.id
    async with async_session_factory() as session:
        registered = await user_service.get_user_by_telegram(session, tid)
    if registered is None:
        await _edit_or_reply(
            query.message,
            t("error.register_first"),
            reply_markup=with_back_to_main(InlineKeyboardMarkup([])),
        )
        return
    if not await telegram_channel_service.user_passes_membership_gate(context.bot, tid):
        join_kb = (
            await telegram_channel_service.join_channel_keyboard_async(context.bot)
            or InlineKeyboardMarkup([])
        )
        await _edit_or_reply(
            query.message,
            t("membership.required_html"),
            reply_markup=with_back_to_main(join_kb),
            parse_mode="HTML",
        )
        return
    for_rial = query.data == "start:rial"
    await _edit_or_reply(
        query.message,
        await _listings_channel_message_body_async(context.bot, for_rial=for_rial),
        reply_markup=await _listings_channel_cta_keyboard_async(context.bot),
        parse_mode="HTML",
    )


async def account_delete_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if (
        query is None
        or query.data is None
        or query.message is None
        or query.from_user is None
    ):
        return

    tid = query.from_user.id
    if not await telegram_channel_service.user_passes_membership_gate(context.bot, tid):
        await query.answer()
        join_kb = (
            await telegram_channel_service.join_channel_keyboard_async(context.bot)
            or InlineKeyboardMarkup([])
        )
        await _edit_or_reply(
            query.message,
            t("membership.required_html"),
            reply_markup=with_back_to_main(join_kb),
            parse_mode="HTML",
        )
        return

    if query.data == "account:delete":
        await query.answer()
        await _edit_or_reply(
            query.message,
            t("account.delete_confirm"),
            reply_markup=delete_confirm_keyboard(),
        )
        return

    await query.answer()

    if query.data == "account:delete_no":
        await _edit_or_reply(
            query.message,
            t("account.delete_cancelled"),
            reply_markup=main_menu_keyboard(),
        )
        return

    if query.data != "account:delete_yes":
        return

    ok = await delete_user_data(tid, context.bot)
    back_only = with_back_to_main(InlineKeyboardMarkup([]))
    if ok:
        await _edit_or_reply(
            query.message,
            t("account.deleted"),
            reply_markup=back_only,
        )
    else:
        await _edit_or_reply(
            query.message,
            t("account.nothing_stored"),
            reply_markup=back_only,
        )


async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    tid = update.effective_user.id
    if not await telegram_channel_service.user_passes_membership_gate(context.bot, tid):
        join_kb = (
            await telegram_channel_service.join_channel_keyboard_async(context.bot)
            or InlineKeyboardMarkup([])
        )
        await update.message.reply_text(
            t("membership.required_html"),
            reply_markup=with_back_to_main(join_kb),
            parse_mode="HTML",
        )
        return
    ok = await delete_user_data(tid, context.bot)
    if ok:
        await update.message.reply_text(t("account.deleted_short"))
    else:
        await update.message.reply_text(t("account.nothing_stored"))


async def on_post_init(_application: Application) -> None:
    await init_db()


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set (see .env.example)")
    if not settings.effective_listings_channel_id():
        raise SystemExit(
            "TELEGRAM_LISTINGS_CHANNEL_ID is required (listings channel; see .env.example)"
        )

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(on_post_init)
        .build()
    )
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("delete", delete_cmd))
    application.add_handler(
        CallbackQueryHandler(consent_callback, pattern=r"^consent:(yes|no)$")
    )
    application.add_handler(
        CallbackQueryHandler(rates_spot_callback, pattern=r"^rates:spot$")
    )
    application.add_handler(
        CallbackQueryHandler(listing_rial_callback, pattern=r"^rial:\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(account_manage_callback, pattern=r"^account:manage$")
    )
    application.add_handler(
        CallbackQueryHandler(offer_action_callback, pattern=r"^offer:(del|sold):\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(
            account_delete_callback,
            pattern=r"^account:(delete|delete_yes|delete_no)$",
        )
    )
    application.add_handler(build_sell_conversation_handler())
    application.add_handler(
        CallbackQueryHandler(menu_main_callback, pattern=rf"^{MENU_MAIN_CALLBACK}$")
    )
    application.add_handler(
        CallbackQueryHandler(buy_flow_callback, pattern=BUY_FLOW_CALLBACK_PATTERN)
    )
    application.add_handler(
        CallbackQueryHandler(start_menu_callback, pattern=r"^start:(2|rial)$")
    )
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
