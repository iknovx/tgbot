from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.screens import SCREENS


def main_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=screen.title, callback_data=f"show:{key}")]
        for key, screen in SCREENS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def screen_keyboard(screen_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Refresh", callback_data=f"show:{screen_key}"),
            InlineKeyboardButton(text="🏠 Menu", callback_data="menu"),
        ],
    ])