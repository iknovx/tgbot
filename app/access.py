from aiogram.types import CallbackQuery, Message

from app.config import settings


def is_owner(user_id: int | None) -> bool:
    return user_id == settings.owner_id


async def deny_message(message: Message) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        await message.answer("⛔ Access denied.")


async def deny_callback(callback: CallbackQuery) -> bool:
    """Returns True if access was denied (caller should stop)."""
    if is_owner(callback.from_user.id if callback.from_user else None):
        return False
    await callback.answer("⛔ Access denied.", show_alert=True)
    return True