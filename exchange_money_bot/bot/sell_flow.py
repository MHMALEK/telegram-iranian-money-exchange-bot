"""چندمرحله‌ای فروش ارز (دکمهٔ اول منو)."""

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
from exchange_money_bot.database import async_session_factory
from exchange_money_bot.services import sell_offers as sell_offers_service
from exchange_money_bot.services import users as user_service

logger = logging.getLogger(__name__)

SELL_AMOUNT, SELL_CURRENCY, SELL_CONFIRM = range(3)


def _currency_label(code: str) -> str:
    return f"{sell_offers_service.currency_label_fa(code)} ({code})"


def _parse_integer_amount(text: str) -> Optional[int]:
    """فقط ارقام انگلیسی 0-9؛ فارسی/عربی و هر کاراکتر دیگر رد می‌شود."""
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
                [InlineKeyboardButton("یورو (EUR)", callback_data="sell:ccy:EUR")],
                [InlineKeyboardButton("دلار (USD)", callback_data="sell:ccy:USD")],
                [InlineKeyboardButton("تتر (USDT)", callback_data="sell:ccy:USDT")],
            ]
        )
    )


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return with_back_to_main(
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("تایید و ثبت", callback_data="sell:submit"),
                    InlineKeyboardButton("انصراف", callback_data="sell:abort"),
                ],
            ]
        )
    )


async def sell_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return ConversationHandler.END
    await query.answer()
    async with async_session_factory() as session:
        registered = await user_service.get_user_by_telegram(session, query.from_user.id)
    if registered is None:
        await query.message.reply_text("برای فروش ارز ابتدا با /start ثبت‌نام کنید.")
        return ConversationHandler.END
    context.user_data.pop("sell_amount", None)
    context.user_data.pop("sell_currency", None)
    await query.message.reply_text(
        "مبلغی را که می‌خواهید بفروشید وارد کنید.\n\n"
        "فقط با اعداد انگلیسی (0 تا 9)، بدون فاصله، ویرگول یا نقطه.\n"
        "مثال: 100 یا 1000 یا 150\n\n"
        "برای لغو این فرم: /cancel",
        reply_markup=with_back_to_main(InlineKeyboardMarkup([])),
    )
    return SELL_AMOUNT


async def sell_receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return SELL_AMOUNT
    text = update.message.text or ""
    amount = _parse_integer_amount(text)
    if amount is None:
        await update.message.reply_text(
            "عدد نامعتبر است. فقط ارقام انگلیسی 0-9، بدون فاصله و بدون نقطه. دوباره بفرستید.",
            reply_markup=with_back_to_main(InlineKeyboardMarkup([])),
        )
        return SELL_AMOUNT
    context.user_data["sell_amount"] = amount
    await update.message.reply_text(
        "ارز را انتخاب کنید:",
        reply_markup=_currency_keyboard(),
    )
    return SELL_CURRENCY


async def sell_currency_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text(
            "لطفاً با یکی از دکمه‌ها، ارز را انتخاب کنید.",
            reply_markup=_currency_keyboard(),
        )
    return SELL_CURRENCY


async def sell_currency_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.message is None or query.data is None or query.from_user is None:
        return ConversationHandler.END
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
            "خطا: مبلغ ذخیره نشد. دوباره از منو «فروش» را بزنید.",
            reply_markup=main_menu_keyboard(),
        )
        context.user_data.clear()
        return ConversationHandler.END
    display_name = query.from_user.full_name or "—"
    uname = f"@{query.from_user.username}" if query.from_user.username else "ندارد"
    summary = (
        "خلاصهٔ آگهی فروش:\n\n"
        f"مبلغ: {amount}\n"
        f"ارز: {_currency_label(code)}\n"
        f"نام نمایشی: {display_name}\n"
        f"یوزرنیم تلگرام: {uname}\n\n"
        "اگر درست است «تایید و ثبت» را بزنید؛ وگرنه «انصراف»."
    )
    await query.message.reply_text(summary, reply_markup=_confirm_keyboard())
    return SELL_CONFIRM


async def sell_confirm_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text(
            "لطفاً با دکمهٔ «تایید و ثبت» یا «انصراف» پاسخ دهید.",
            reply_markup=_confirm_keyboard(),
        )
    return SELL_CONFIRM


async def sell_submit_or_abort(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.message is None or query.data is None or query.from_user is None:
        return ConversationHandler.END
    await query.answer()
    if query.data == "sell:abort":
        context.user_data.clear()
        await query.message.reply_text(
            "ثبت آگهی لغو شد.\nیکی از گزینه‌های منو را انتخاب کنید:",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END
    if query.data != "sell:submit":
        return SELL_CONFIRM
    amount = context.user_data.get("sell_amount")
    currency = context.user_data.get("sell_currency")
    if not isinstance(amount, int) or not isinstance(currency, str):
        await query.message.reply_text(
            "خطا در داده‌ها. دوباره از منو شروع کنید.",
            reply_markup=main_menu_keyboard(),
        )
        context.user_data.clear()
        return ConversationHandler.END
    u = query.from_user
    async with async_session_factory() as session:
        db_user = await user_service.get_user_by_telegram(session, u.id)
        if db_user is None:
            await query.message.reply_text(
                "کاربر یافت نشد. /start را بزنید.",
                reply_markup=main_menu_keyboard(),
            )
            context.user_data.clear()
            return ConversationHandler.END
        display_name = u.full_name or (db_user.first_name or "—")
        try:
            await sell_offers_service.create_sell_offer(
                session,
                user_id=db_user.id,
                telegram_id=u.id,
                telegram_username=u.username,
                seller_display_name=display_name,
                amount=amount,
                currency=currency,
            )
        except ValueError as e:
            logger.warning("sell offer validation: %s", e)
            await query.message.reply_text(
                "ذخیره نشد. دوباره تلاش کنید.",
                reply_markup=main_menu_keyboard(),
            )
            context.user_data.clear()
            return ConversationHandler.END
    context.user_data.clear()
    await query.message.reply_text(
        "ثبت شما انجام شد.\n"
        f"مبلغ {amount} {_currency_label(currency)} برای فروش در فهرست فروشندگان نمایش داده می‌شود.\n"
        "اگر کسی مایل به خرید باشد، با شما تماس می‌گیرد.",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def sell_conversation_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("sell_amount", None)
    context.user_data.pop("sell_currency", None)
    if update.message:
        await update.message.reply_text(
            "فرم فروش لغو شد. از منوی زیر ادامه دهید:",
            reply_markup=main_menu_keyboard(),
        )
    return ConversationHandler.END


async def sell_buy_flow_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """خروج از فرم فروش اگر کاربر حین گفتگو دکمهٔ خرید (انتخاب ارز / فهرست / صفحه) بزند."""
    query = update.callback_query
    if query is None or query.message is None or query.from_user is None:
        return ConversationHandler.END
    context.user_data.pop("sell_amount", None)
    context.user_data.pop("sell_currency", None)
    from exchange_money_bot.bot.main import execute_buy_flow_callback

    await execute_buy_flow_callback(query)
    return ConversationHandler.END


async def sell_menu_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.message is None:
        return ConversationHandler.END
    await query.answer()
    context.user_data.pop("sell_amount", None)
    context.user_data.pop("sell_currency", None)
    from exchange_money_bot.bot.main import apply_home_screen

    await apply_home_screen(query)
    return ConversationHandler.END


def build_sell_conversation_handler() -> ConversationHandler:
    menu_main_handler = CallbackQueryHandler(
        sell_menu_main,
        pattern=rf"^{MENU_MAIN_CALLBACK}$",
    )
    buy_flow_handler = CallbackQueryHandler(
        sell_buy_flow_fallback,
        pattern=r"^buy:(choose|ccy:(USDT|EUR|USD)|cat:(USDT|EUR|USD):\d+)$",
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
                    pattern=r"^sell:ccy:(EUR|USD|USDT)$",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_currency_reminder),
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
