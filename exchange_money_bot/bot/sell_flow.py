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

SELL_AMOUNT, SELL_CURRENCY, SELL_DESCRIPTION, SELL_PAYMENT, SELL_CONFIRM = range(5)

MAX_DESCRIPTION_LEN = sell_offers_service.MAX_OFFER_DESCRIPTION_LEN

_PAYMENT_TOGGLE_PATTERN = (
    r"^sell:pay:(cash_in_person|bank|crypto|other)$"
)


def _listing_direction(context: ContextTypes.DEFAULT_TYPE) -> str:
    v = context.user_data.get("listing_direction")
    if v == sell_offers_service.LISTING_RIAL_TO_FX:
        return sell_offers_service.LISTING_RIAL_TO_FX
    return sell_offers_service.LISTING_FX_TO_RIAL


def _amount_prompt_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    if _listing_direction(context) == sell_offers_service.LISTING_RIAL_TO_FX:
        return t("sell.amount_prompt_rial_to_fx")
    return t("sell.amount_prompt")


def _amount_reply_parse_mode(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    if _listing_direction(context) == sell_offers_service.LISTING_RIAL_TO_FX:
        return "HTML"
    return None


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


def _payment_codes_from_user_data(context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    raw = context.user_data.get("sell_payment_methods")
    if not isinstance(raw, list):
        return []
    return [c for c in raw if isinstance(c, str)]


def _payment_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    sel_set = set(selected)

    def lbl(code: str) -> str:
        mark = "✓ " if code in sel_set else "○ "
        return mark + sell_offers_service.payment_method_label_fa(code)

    codes = sell_offers_service.PAYMENT_METHOD_CODES_ORDER
    return with_back_to_main(
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(lbl(codes[0]), callback_data=f"sell:pay:{codes[0]}"),
                    InlineKeyboardButton(lbl(codes[1]), callback_data=f"sell:pay:{codes[1]}"),
                ],
                [
                    InlineKeyboardButton(lbl(codes[2]), callback_data=f"sell:pay:{codes[2]}"),
                    InlineKeyboardButton(lbl(codes[3]), callback_data=f"sell:pay:{codes[3]}"),
                ],
                [
                    InlineKeyboardButton(
                        t("sell.payment_btn_done"),
                        callback_data="sell:pay:done",
                    ),
                ],
            ]
        )
    )


async def _send_payment_prompt(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["sell_payment_methods"] = []
    await message.reply_text(
        t("sell.payment_prompt"),
        reply_markup=_payment_keyboard([]),
        parse_mode="HTML",
    )


def _sell_summary_text(
    *,
    amount: int,
    code: str,
    display_name: str,
    uname: str,
    description: Optional[str],
    payment_methods: list[str],
    listing_direction: str,
) -> str:
    if description:
        desc_block = t("sell.summary_description", desc=description)
    else:
        desc_block = t("sell.summary_no_description")
    pay_block = t(
        "sell.summary_payment",
        methods=sell_offers_service.format_payment_methods_summary_fa(payment_methods),
    )
    summary_key = (
        "sell.summary_rial_to_fx"
        if listing_direction == sell_offers_service.LISTING_RIAL_TO_FX
        else "sell.summary_fx_to_rial"
    )
    return t(
        summary_key,
        amount=amount,
        currency_label=_currency_label(code),
        display_name=display_name,
        uname=uname,
        description_block=desc_block,
        payment_block=pay_block,
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
    context.user_data.pop("sell_payment_methods", None)
    context.user_data.pop("listing_direction", None)
    if query.data == "start:3":
        context.user_data["listing_direction"] = sell_offers_service.LISTING_RIAL_TO_FX
    else:
        context.user_data["listing_direction"] = sell_offers_service.LISTING_FX_TO_RIAL
    await query.message.reply_text(
        _amount_prompt_text(context),
        reply_markup=with_back_to_main(InlineKeyboardMarkup([])),
        parse_mode=_amount_reply_parse_mode(context),
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
            parse_mode=_amount_reply_parse_mode(context),
        )
        return SELL_AMOUNT
    context.user_data["sell_amount"] = amount
    pick_key = (
        "sell.pick_currency_rial_to_fx"
        if _listing_direction(context) == sell_offers_service.LISTING_RIAL_TO_FX
        else "sell.pick_currency"
    )
    await update.message.reply_text(
        t(pick_key),
        reply_markup=_currency_keyboard(),
    )
    return SELL_CURRENCY


async def sell_currency_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    end = await _end_sell_if_not_member(update, context)
    if end is not None:
        return end
    if update.message:
        rem_key = (
            "sell.currency_reminder_rial_to_fx"
            if _listing_direction(context) == sell_offers_service.LISTING_RIAL_TO_FX
            else "sell.currency_reminder"
        )
        await update.message.reply_text(
            t(rem_key),
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
    await _send_payment_prompt(query.message, context)
    return SELL_PAYMENT


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
    await _send_payment_prompt(update.message, context)
    return SELL_PAYMENT


async def sell_payment_toggle(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None or query.message is None or query.data is None:
        return ConversationHandler.END
    end = await _end_sell_if_not_member(update, context)
    if end is not None:
        await query.answer()
        return end
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "sell" or parts[1] != "pay":
        return SELL_PAYMENT
    code = parts[2]
    if code not in sell_offers_service.ALLOWED_PAYMENT_METHODS:
        return SELL_PAYMENT
    sel = _payment_codes_from_user_data(context)
    if code in sel:
        sel = [c for c in sel if c != code]
    else:
        sel = [*sel, code]
    context.user_data["sell_payment_methods"] = sel
    try:
        await query.edit_message_reply_markup(reply_markup=_payment_keyboard(sel))
    except Exception:
        logger.debug("edit_message_reply_markup failed (payment toggles)", exc_info=True)
    return SELL_PAYMENT


async def sell_payment_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return ConversationHandler.END
    end = await _end_sell_if_not_member(update, context)
    if end is not None:
        await query.answer()
        return end
    sel = _payment_codes_from_user_data(context)
    try:
        normalized = sell_offers_service.normalize_payment_methods(sel)
    except ValueError:
        await query.answer(t("sell.payment_need_one"), show_alert=True)
        return SELL_PAYMENT
    await query.answer()
    context.user_data["sell_payment_methods"] = normalized
    amount = context.user_data.get("sell_amount")
    code = context.user_data.get("sell_currency")
    if not isinstance(amount, int) or not isinstance(code, str):
        await query.message.reply_text(
            t("error.amount_lost"),
            reply_markup=main_menu_keyboard(),
        )
        context.user_data.clear()
        return ConversationHandler.END
    desc_raw = context.user_data.get("sell_description")
    description = desc_raw if isinstance(desc_raw, str) else None
    u = query.from_user
    display_name = u.full_name or t("sell.display_fallback")
    uname = f"@{u.username}" if u.username else t("sell.username_none")
    await query.message.reply_text(
        _sell_summary_text(
            amount=amount,
            code=code,
            display_name=display_name,
            uname=uname,
            description=description,
            payment_methods=normalized,
            listing_direction=_listing_direction(context),
        ),
        reply_markup=_confirm_keyboard(),
    )
    return SELL_CONFIRM


async def sell_payment_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    end = await _end_sell_if_not_member(update, context)
    if end is not None:
        return end
    if update.message:
        sel = _payment_codes_from_user_data(context)
        await update.message.reply_text(
            t("sell.payment_reminder"),
            reply_markup=_payment_keyboard(sel),
        )
    return SELL_PAYMENT


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
        pm = _payment_codes_from_user_data(context)
        u = update.effective_user
        if (
            isinstance(amount, int)
            and isinstance(code, str)
            and u is not None
            and (desc is None or isinstance(desc, str))
            and pm
        ):
            try:
                pm_norm = sell_offers_service.normalize_payment_methods(pm)
            except ValueError:
                pm_norm = None
            if pm_norm:
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
                        payment_methods=pm_norm,
                        listing_direction=_listing_direction(context),
                    ),
                    reply_markup=_confirm_keyboard(),
                )
            else:
                await update.message.reply_text(
                    t("sell.confirm_reminder"),
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
        pm_raw = context.user_data.get("sell_payment_methods")
        if not isinstance(pm_raw, list) or not pm_raw:
            await query.message.reply_text(
                t("error.data_lost"),
                reply_markup=main_menu_keyboard(),
            )
            context.user_data.clear()
            return ConversationHandler.END
        try:
            payment_methods = sell_offers_service.normalize_payment_methods(pm_raw)
        except ValueError:
            await query.message.reply_text(
                t("error.data_lost"),
                reply_markup=main_menu_keyboard(),
            )
            context.user_data.clear()
            return ConversationHandler.END
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
                payment_methods=payment_methods,
                listing_direction=_listing_direction(context),
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
    saved_direction = _listing_direction(context)
    context.user_data.clear()
    if settings.effective_listings_channel_id():
        channel_note = t("sell.success_channel_on_html")
    else:
        channel_note = t("sell.success_channel_off")
    succ_key = (
        "sell.success_intro_rial_to_fx"
        if saved_direction == sell_offers_service.LISTING_RIAL_TO_FX
        else "sell.success_intro_fx_to_rial"
    )
    await query.message.reply_text(
        t(
            succ_key,
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
    context.user_data.pop("sell_payment_methods", None)
    context.user_data.pop("listing_direction", None)
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
    context.user_data.pop("sell_payment_methods", None)
    context.user_data.pop("listing_direction", None)
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
    context.user_data.pop("sell_payment_methods", None)
    context.user_data.pop("listing_direction", None)
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
        entry_points=[
            CallbackQueryHandler(sell_entry, pattern=r"^start:(1|3)$"),
        ],
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
            SELL_PAYMENT: [
                CallbackQueryHandler(sell_payment_done, pattern=r"^sell:pay:done$"),
                CallbackQueryHandler(sell_payment_toggle, pattern=_PAYMENT_TOGGLE_PATTERN),
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_payment_reminder),
                MessageHandler(~filters.COMMAND, sell_payment_reminder),
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
