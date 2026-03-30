from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from exchange_money_bot.config import settings

# Callback for «بازگشت به منوی اصلی» — must match ConversationHandler fallback in sell_flow.
MENU_MAIN_CALLBACK = "menu:main"


def with_back_to_main(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    """Append a single row so users can return to the same screen as after /start (registered or consent)."""
    rows = [list(row) for row in markup.inline_keyboard]
    rows.append(
        [
            InlineKeyboardButton(
                "بازگشت به منوی اصلی",
                callback_data=MENU_MAIN_CALLBACK,
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def buyer_currency_pick_keyboard() -> InlineKeyboardMarkup:
    """قبل از فهرست خرید: انتخاب یورو / دلار / تتر."""
    return with_back_to_main(
        InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("یورو (EUR)", callback_data="buy:ccy:EUR")],
                [InlineKeyboardButton("دلار (USD)", callback_data="buy:ccy:USD")],
                [InlineKeyboardButton("تتر (USDT)", callback_data="buy:ccy:USDT")],
            ]
        )
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    settings.start_button_1_text,
                    callback_data="start:1",
                ),
            ],
            [
                InlineKeyboardButton(
                    settings.start_button_2_text,
                    callback_data="start:2",
                ),
            ],
            [
                InlineKeyboardButton(
                    "آگهی‌های من",
                    callback_data="account:manage",
                ),
            ],
            [
                InlineKeyboardButton(
                    "حذف داده‌های من",
                    callback_data="account:delete",
                ),
            ],
        ]
    )
