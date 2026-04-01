from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from exchange_money_bot.i18n import t

# Callback for "back to main menu" — must match ConversationHandler fallback in sell_flow.
MENU_MAIN_CALLBACK = "menu:main"


def with_back_to_main(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    """Append a single row so users can return to the same screen as after /start (registered or consent)."""
    rows = [list(row) for row in markup.inline_keyboard]
    rows.append(
        [
            InlineKeyboardButton(
                t("keyboard.back_main"),
                callback_data=MENU_MAIN_CALLBACK,
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("keyboard.menu_fx"), callback_data="start:1")],
            [
                InlineKeyboardButton(
                    t("keyboard.menu_rial_to_fx"),
                    callback_data="start:3",
                )
            ],
            [
                InlineKeyboardButton(
                    t("keyboard.menu_my_offers"),
                    callback_data="account:manage",
                )
            ],
            [InlineKeyboardButton(t("keyboard.menu_rial"), callback_data="start:rial")],
            [InlineKeyboardButton(t("keyboard.menu_spot_rates"), callback_data="rates:spot")],

            [
                InlineKeyboardButton(
                    t("keyboard.menu_delete_account"),
                    callback_data="account:delete",
                )
            ],
        ]
    )
