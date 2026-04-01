"""Multi-step sell flow (first main-menu path)."""

from __future__ import annotations

import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from exchange_money_bot.bot.keyboards import (
    MENU_MAIN_CALLBACK,
    main_menu_keyboard,
    with_back_to_main,
)
from exchange_money_bot.config import settings
from exchange_money_bot.database import async_session_factory
from exchange_money_bot.i18n import t
from exchange_money_bot.services import sell_offers as sell_offers_service
from exchange_money_bot.services import telegram_channel as telegram_channel_service
from exchange_money_bot.services import users as user_service

logger = logging.getLogger(__name__)

SELL_AMOUNT, SELL_CURRENCY, SELL_DESCRIPTION, SELL_CONFIRM = range(4)

MAX_DESCRIPTION_LEN = sell_offers_service.MAX_OFFER_DESCRIPTION_LEN


async def _end_sell_if_not_member(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> Optional[int]:
    """If the membership gate applies and the user no longer passes (group/channel), end the flow."""
    u = update.effective_user
    if u is None:
        return ConversationHandler.END
    if not settings.membership_gate_active():
        return None
    if await telegram_channel_service.user_passes_membership_gate(context.bot, u.id):
        return None
    join_kb = (
        await telegram_channel_service.join_channel_keyboard_async(context.bot)
        or InlineKeyboardMarkup([])
    )
    markup = with_back_to_main(join_kb)
    text = t("membership.sell_gate_html")
    if update.message:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup)
    elif update.callback_query and update.callback_query.message:
        await update.callback_query.message.reply_text(
            text, parse_mode="HTML", reply_markup=markup
        )
    context.user_data.clear()
    return ConversationHandler.END


def _currency_label(code: str) -> str:
    return f"{sell_offers_service.currency_label_fa(code)} ({code})"


def _parse_integer_amount(text: str) -> Optional[int]:
    """ASCII digits 0-9 only; Persian/Arabic numerals and any other character are rejected."""
    s = text.strip()
    if not s or any(ch.isspace() for ch in s):
        return None
    if not s.isascii() or not all("0" <= c <= "9" for c in s):
        return None
    value = int(s)
    if value <= 0:
        return None
    return value


def _currency_keyboard() -> InlineKeyboardMarkup:
    return with_back_to_main(
        InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(t("sell.btn_eur"), callback_data="sell:ccy:EUR")],
                [InlineKeyboardButton(t("sell.btn_usd"), callback_data="sell:ccy:USD")],
            ]
        )
    )


def _description_keyboard() -> InlineKeyboardMarkup:
    return with_back_to_main(
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        t("sell.btn_desc_skip"), callback_data="sell:desc:skip"
                    ),
                ],
            ]
        )
    )


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return with_back_to_main(
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(t("sell.btn_abort"), callback_data="sell:abort"),
                    InlineKeyboardButton(t("sell.btn_submit"), callback_data="sell:submit"),
                ],
            ]
        )
    )


def _sell_summary_text(
    *,
    amount: int,
    code: str,
    display_name: str,
    uname: str,
    description: Optional[str],
) -> str:
    if description:
        desc_block = t("sell.summary_description", desc=description)
    else:
        desc_block = t("sell.summary_no_description")
    return t(
        "sell.summary",
        amount=amount,
        currency_label=_currency_label(code),
        display_name=display_name,
        uname=uname,
        description_block=desc_block,
    )


async def sell_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return ConversationHandler.END
    await query.answer()
    async with async_session_factory() as session:
        registered = await user_service.get_user_by_telegram(session, query.from_user.id)
    if registered is None:
        await query.message.reply_text(t("sell.register_first"))
        return ConversationHandler.END
    if not await telegram_channel_service.user_passes_membership_gate(
        context.bot, query.from_user.id
    ):
        join_kb = (
            await telegram_channel_service.join_channel_keyboard_async(context.bot)
            or InlineKeyboardMarkup([])
        )
        await query.message.reply_text(
            t("membership.sell_gate_html"),
            parse_mode="HTML",
            reply_markup=with_back_to_main(join_kb),
        )
        return ConversationHandler.END
    context.user_data.pop("sell_amount", None)
    context.user_data.pop("sell_currency", None)
    context.user_data.pop("sell_description", None)
    await query.message.reply_text(
        t("sell.amount_prompt"),
        reply_markup=with_back_to_main(InlineKeyboardMarkup([])),
    )
    return SELL_AMOUNT


async def sell_receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    end = await _end_sell_if_not_member(update, context)
    if end is not None:
        return end
    if update.message is None:
        return SELL_AMOUNT
    text = update.message.text or ""
    amount = _parse_integer_amount(text)
    if amount is None:
        await update.message.reply_text(
            t("sell.amount_invalid"),
            reply_markup=with_back_to_main(InlineKeyboardMarkup([])),
        )
        return SELL_AMOUNT
    context.user_data["sell_amount"] = amount
    await update.message.reply_text(
        t("sell.pick_currency"),
        reply_markup=_currency_keyboard(),
    )
    return SELL_CURRENCY


async def sell_currency_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    end = await _end_sell_if_not_member(update, context)
    if end is not None:
        return end
    if update.message:
        await update.message.reply_text(
            t("sell.currency_reminder"),
            reply_markup=_currency_keyboard(),
        )
    return SELL_CURRENCY


async def sell_currency_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.message is None or query.data is None or query.from_user is None:
        return ConversationHandler.END
    end = await _end_sell_if_not_member(update, context)
    if end is not None:
        await query.answer()
        return end
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "sell" or parts[1] != "ccy":
        return SELL_CURRENCY
    code = parts[2]
    if code not in sell_offers_service.ALLOWED_CURRENCIES:
        return SELL_CURRENCY
    context.user_data["sell_currency"] = code
    amount = context.user_data.get("sell_amount")
    if not isinstance(amount, int):
        await query.message.reply_text(
            t("error.amount_lost"),
            reply_markup=main_menu_keyboard(),
        )
        context.user_data.clear()
        return ConversationHandler.END
    display_name = query.from_user.full_name or t("sell.display_fallback")
    uname = (
        f"@{query.from_user.username}"
        if query.from_user.username
        else t("sell.username_none")
    )
    await query.message.reply_text(
        t("sell.description_prompt", max=MAX_DESCRIPTION_LEN),
        reply_markup=_description_keyboard(),
    )
    return SELL_DESCRIPTION


async def sell_description_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return ConversationHandler.END
    end = await _end_sell_if_not_member(update, context)
    if end is not None:
        await query.answer()
        return end
    await query.answer()
    amount = context.user_data.get("sell_amount")
    code = context.user_data.get("sell_currency")
    if not isinstance(amount, int) or not isinstance(code, str):
        await query.message.reply_text(
            t("error.amount_lost"),
            reply_markup=main_menu_keyboard(),
        )
        context.user_data.clear()
        return ConversationHandler.END
    context.user_data["sell_description"] = None
    display_name = query.from_user.full_name or t("sell.display_fallback")
    uname = (
        f"@{query.from_user.username}"
        if query.from_user.username
        else t("sell.username_none")
    )
    await query.message.reply_text(
        _sell_summary_text(
            amount=amount,
            code=code,
            display_name=display_name,
            uname=uname,
            description=None,
        ),
        reply_markup=_confirm_keyboard(),
    )
    return SELL_CONFIRM


async def sell_receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    end = await _end_sell_if_not_member(update, context)
    if end is not None:
        return end
    if update.message is None:
        return SELL_DESCRIPTION
    raw = update.message.text or ""
    text = raw.strip()
    if not text:
        await update.message.reply_text(
            t("sell.description_empty"),
            reply_markup=_description_keyboard(),
        )
        return SELL_DESCRIPTION
    if len(text) > MAX_DESCRIPTION_LEN:
        await update.message.reply_text(
            t("sell.description_too_long", max=MAX_DESCRIPTION_LEN),
            reply_markup=_description_keyboard(),
        )
        return SELL_DESCRIPTION
    amount = context.user_data.get("sell_amount")
    code = context.user_data.get("sell_currency")
    if not isinstance(amount, int) or not isinstance(code, str):
        await update.message.reply_text(
            t("error.amount_lost"),
            reply_markup=main_menu_keyboard(),
        )
        context.user_data.clear()
        return ConversationHandler.END
    context.user_data["sell_description"] = text
    u = update.effective_user
    display_name = (u.full_name if u else None) or t("sell.display_fallback")
    uname = (
        f"@{u.username}" if u and u.username else t("sell.username_none")
    )
    await update.message.reply_text(
        _sell_summary_text(
            amount=amount,
            code=code,
            display_name=display_name,
            uname=uname,
            description=text,
        ),
        reply_markup=_confirm_keyboard(),
    )
    return SELL_CONFIRM


async def sell_description_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    end = await _end_sell_if_not_member(update, context)
    if end is not None:
        return end
    if update.message:
        await update.message.reply_text(
            t("sell.description_reminder", max=MAX_DESCRIPTION_LEN),
            reply_markup=_description_keyboard(),
        )
    return SELL_DESCRIPTION


async def sell_confirm_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    end = await _end_sell_if_not_member(update, context)
    if end is not None:
        return end
    if update.message:
        amount = context.user_data.get("sell_amount")
        code = context.user_data.get("sell_currency")
        desc = context.user_data.get("sell_description")
        u = update.effective_user
        if (
            isinstance(amount, int)
            and isinstance(code, str)
            and u is not None
            and (desc is None or isinstance(desc, str))
        ):
            display_name = u.full_name or t("sell.display_fallback")
            uname = (
                f"@{u.username}" if u.username else t("sell.username_none")
            )
            await update.message.reply_text(
                _sell_summary_text(
                    amount=amount,
                    code=code,
                    display_name=display_name,
                    uname=uname,
                    description=desc if desc else None,
                ),
                reply_markup=_confirm_keyboard(),
            )
        else:
            await update.message.reply_text(
                t("sell.confirm_reminder"),
                reply_markup=_confirm_keyboard(),
            )
    return SELL_CONFIRM


async def sell_submit_or_abort(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.message is None or query.data is None or query.from_user is None:
        return ConversationHandler.END
    end = await _end_sell_if_not_member(update, context)
    if end is not None:
        await query.answer()
        return end
    await query.answer()
    if query.data == "sell:abort":
        context.user_data.clear()
        await query.message.reply_text(
            t("sell.aborted"),
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END
    if query.data != "sell:submit":
        return SELL_CONFIRM
    amount = context.user_data.get("sell_amount")
    currency = context.user_data.get("sell_currency")
    if not isinstance(amount, int) or not isinstance(currency, str):
        await query.message.reply_text(
            t("error.data_lost"),
            reply_markup=main_menu_keyboard(),
        )
        context.user_data.clear()
        return ConversationHandler.END
    u = query.from_user
    async with async_session_factory() as session:
        db_user = await user_service.get_user_by_telegram(session, u.id)
        if db_user is None:
            await query.message.reply_text(
                t("error.user_not_found"),
                reply_markup=main_menu_keyboard(),
            )
            context.user_data.clear()
            return ConversationHandler.END
        display_name = u.full_name or (db_user.first_name or "—")
        desc_raw = context.user_data.get("sell_description")
        description = desc_raw if isinstance(desc_raw, str) else None
        try:
            offer = await sell_offers_service.create_sell_offer(
                session,
                user_id=db_user.id,
                telegram_id=u.id,
                telegram_username=u.username,
                seller_display_name=display_name,
                amount=amount,
                currency=currency,
                description=description,
            )
        except ValueError as e:
            logger.warning("sell offer validation: %s", e)
            await query.message.reply_text(
                t("error.offer_save"),
                reply_markup=main_menu_keyboard(),
            )
            context.user_data.clear()
            return ConversationHandler.END
    listing_mid = await telegram_channel_service.post_offer_to_listings_channel(
        context.bot, offer
    )
    if listing_mid is not None:
        async with async_session_factory() as session:
            await sell_offers_service.set_listings_channel_message_id(
                session, offer.id, listing_mid
            )
    context.user_data.clear()
    if settings.effective_listings_channel_id():
        channel_note = t("sell.success_channel_on_html")
    else:
        channel_note = t("sell.success_channel_off")
    await query.message.reply_text(
        t(
            "sell.success_intro",
            amount=amount,
            currency_label=_currency_label(currency),
            channel_note=channel_note,
        ),
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def sell_conversation_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("sell_amount", None)
    context.user_data.pop("sell_currency", None)
    context.user_data.pop("sell_description", None)
    if update.message:
        await update.message.reply_text(
            t("sell.cancelled_cmd"),
            reply_markup=main_menu_keyboard(),
        )
    return ConversationHandler.END


async def sell_buy_flow_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """End sell conversation when user taps buy flow (currency pick / catalog / page) mid-dialog."""
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return ConversationHandler.END
    context.user_data.pop("sell_amount", None)
    context.user_data.pop("sell_currency", None)
    context.user_data.pop("sell_description", None)
    from exchange_money_bot.bot.main import execute_buy_flow_callback

    await execute_buy_flow_callback(query, context.bot)
    return ConversationHandler.END


async def sell_menu_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.message is None:
        return ConversationHandler.END
    await query.answer()
    context.user_data.pop("sell_amount", None)
    context.user_data.pop("sell_currency", None)
    context.user_data.pop("sell_description", None)
    from exchange_money_bot.bot.main import apply_home_screen

    await apply_home_screen(query, context.bot)
    return ConversationHandler.END


def build_sell_conversation_handler() -> ConversationHandler:
    menu_main_handler = CallbackQueryHandler(
        sell_menu_main,
        pattern=rf"^{MENU_MAIN_CALLBACK}$",
    )
    buy_flow_handler = CallbackQueryHandler(
        sell_buy_flow_fallback,
        pattern=r"^buy:(choose|ccy:(EUR|USD)|cat:(EUR|USD):\d+)$",
    )
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(sell_entry, pattern=r"^start:1$")],
        states={
            SELL_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_amount),
            ],
            SELL_CURRENCY: [
                CallbackQueryHandler(
                    sell_currency_chosen,
                    pattern=r"^sell:ccy:(EUR|USD)$",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_currency_reminder),
            ],
            SELL_DESCRIPTION: [
                CallbackQueryHandler(sell_description_skip, pattern=r"^sell:desc:skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_receive_description),
                MessageHandler(~filters.COMMAND, sell_description_reminder),
            ],
            SELL_CONFIRM: [
                CallbackQueryHandler(
                    sell_submit_or_abort,
                    pattern=r"^sell:(submit|abort)$",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_confirm_reminder),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", sell_conversation_cancel),
            menu_main_handler,
            buy_flow_handler,
        ],
        name="sell_flow",
    )
