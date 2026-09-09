import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.access import deny_callback, deny_message, is_owner
from app.keyboards import main_menu_keyboard, screen_keyboard
from app.screens import SCREENS
from app.texts import main_menu_text

logger = logging.getLogger(__name__)

router = Router()


async def _reply_with_screen(message: Message, screen_key: str) -> None:
    screen = SCREENS[screen_key]
    text = await asyncio.to_thread(screen.builder)
    await message.answer(text, reply_markup=screen_keyboard(screen_key))


@router.message(Command("start", "help"))
async def start_handler(message: Message) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        await deny_message(message)
        return
    await message.answer(main_menu_text(), reply_markup=main_menu_keyboard())


@router.message(Command(*SCREENS.keys()))
async def screen_command_handler(message: Message) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        await deny_message(message)
        return

    # /status@YourBotName в группах — отрезаем имя бота и слэш
    command = (message.text or "").split()[0].lstrip("/").split("@")[0]
    if command not in SCREENS:
        return
    await _reply_with_screen(message, command)


@router.callback_query(F.data.startswith("show:"))
async def show_screen_callback(callback: CallbackQuery) -> None:
    if await deny_callback(callback):
        return

    screen_key = callback.data.split(":", 1)[1]
    if screen_key not in SCREENS or not isinstance(callback.message, Message):
        await callback.answer()
        return

    await callback.answer("Updating…")
    screen = SCREENS[screen_key]
    text = await asyncio.to_thread(screen.builder)
    try:
        await callback.message.edit_text(text, reply_markup=screen_keyboard(screen_key))
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error).lower():
            logger.warning("Could not update %s screen: %s", screen_key, error)


@router.callback_query(F.data == "menu")
async def main_menu_callback(callback: CallbackQuery) -> None:
    if await deny_callback(callback):
        return
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(main_menu_text(), reply_markup=main_menu_keyboard())
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error).lower():
            logger.warning("Could not show main menu: %s", error)