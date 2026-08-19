import asyncio
import html
import json
import logging
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timedelta
import platform
from pathlib import Path
import psutil
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import app.config as config

BOT_TOKEN = config.BOT_TOKEN
OWNER_ID = config.OWNER_ID

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в app/config.py")

if not OWNER_ID:
    raise RuntimeError("OWNER_ID не найден в app/config.py")

CPU_ALERT_THRESHOLD = 85
MEMORY_ALERT_THRESHOLD = 85
TEMP_ALERT_THRESHOLD = 90
ALERT_COOLDOWN_MINUTES = 15
CONSECUTIVE_HIGH_SAMPLES = 2
MONITORING_INTERVAL_SECONDS = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

if not getattr(config, "BOT_TOKEN", None):
    raise RuntimeError("Set BOT_TOKEN in app/config.py before starting the bot.")

router = Router()
last_alert_time: dict[str, datetime] = {}
high_sample_count: defaultdict[str, int] = defaultdict(int)


def is_owner(user_id: int | None) -> bool:
    return user_id == OWNER_ID


async def deny_message(message: Message) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        await message.answer("⛔ Access denied.")


async def deny_callback(callback: CallbackQuery) -> bool:
    if is_owner(callback.from_user.id if callback.from_user else None):
        return False
    await callback.answer("⛔ Access denied.", show_alert=True)
    return True


def format_uptime() -> str:
    total_seconds = int(time.time() - psutil.boot_time())
    days, remainder = divmod(total_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, _ = divmod(remainder, 60)
    parts = ([f"{days}d"] if days else []) + ([f"{hours}h"] if hours else [])
    return " ".join([*parts, f"{minutes}m"])


def get_cpu_temperature() -> float | None:
    system = platform.system()

    if system == "Darwin":  # macOS
        try:
            result = subprocess.run(
                ["ismc", "temp", "-o", "json"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            sensors = json.loads(result.stdout)
            value = sensors.get("CPU Die Average", {}).get("quantity")
            return float(value) if isinstance(value, (int, float)) else None
        except (subprocess.CalledProcessError, FileNotFoundError,
                subprocess.TimeoutExpired, json.JSONDecodeError):
            return None

    if system == "Linux":
        temperatures = psutil.sensors_temperatures()
        for entries in temperatures.values():
            for item in entries:
                if item.current is not None:
                    return item.current

    # В Windows стандартного надёжного API для температуры нет.
    return None


def get_top_processes(limit: int = 8) -> list[dict]:
    processes = []
    for process in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            process.cpu_percent(None)
            processes.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    time.sleep(0.3)
    result = []
    for process in processes:
        try:
            result.append({
                "pid": process.pid,
                "name": process.name(),
                "cpu_percent": process.cpu_percent(None),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(result, key=lambda item: item["cpu_percent"], reverse=True)[:limit]


def bar(percent: float, length: int = 10) -> str:
    filled = max(0, min(length, round(percent / 100 * length)))
    return "█" * filled + "░" * (length - filled)


def build_status_text() -> str:
    cpu = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(Path.home().anchor)
    temperature = get_cpu_temperature()
    lines = [
        "🖥 <b>System status</b>", "",
        f"CPU     {bar(cpu)}  {cpu:.0f}%",
        f"Memory  {bar(memory.percent)}  {memory.percent:.0f}%  ({memory.used // 2**30} / {memory.total // 2**30} GB)",
        f"Disk    {bar(disk.percent)}  {disk.percent:.0f}%  ({disk.used // 2**30} / {disk.total // 2**30} GB)", "",
        f"🌡 Temperature: {f'{temperature:.1f}°C' if temperature is not None else 'unavailable'}",
        f"⏱ Uptime: {format_uptime()}",
    ]
    battery = psutil.sensors_battery()
    if battery:
        source = "🔌 charging" if battery.power_plugged else "🔋 on battery"
        lines.append(f"🔋 Battery: {battery.percent:.0f}% ({source})")
    return "\n".join([*lines, "", f"<i>Updated: {datetime.now():%H:%M:%S}</i>"])


def build_processes_text() -> str:
    lines = ["🔥 <b>Top processes (CPU)</b>", "<pre>"]
    for process in get_top_processes():
        name = html.escape((process["name"] or "unknown")[:22])
        lines.append(f"{name:<22} PID {process['pid']:<7} {process['cpu_percent']:>5.1f}%")
    return "\n".join([*lines, "</pre>"])


def build_network_text() -> str:
    start = psutil.net_io_counters()
    time.sleep(1)
    end = psutil.net_io_counters()
    upload = (end.bytes_sent - start.bytes_sent) / 1024
    download = (end.bytes_recv - start.bytes_recv) / 1024
    return "\n".join([
        "🌐 <b>Network</b>", "",
        f"⬆ Upload:   {upload:.1f} KB/s",
        f"⬇ Download: {download:.1f} KB/s", "",
        f"Total sent:     {end.bytes_sent // 2**20} MB",
        f"Total received: {end.bytes_recv // 2**20} MB",
    ])


def status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="refresh_status")],
        [InlineKeyboardButton(text="🏠 Main menu", callback_data="main_menu")],
    ])


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Check status", callback_data="refresh_status")],
    ])


def main_menu_text() -> str:
    return (
        "🖥 <b>System Monitor Bot</b>\n\n"
        "/status — CPU, memory, disk, temperature, battery\n"
        "/processes — top processes by CPU use\n"
        "/network — current upload/download speed\n\n"
        "Alerts are sent when a metric stays above its threshold."
    )


@router.message(Command("start", "help"))
async def start_handler(message: Message) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        await deny_message(message)
        return
    await message.answer(main_menu_text(), reply_markup=menu_keyboard())


@router.message(Command("status"))
async def status_handler(message: Message) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        await deny_message(message)
        return
    await message.answer(await asyncio.to_thread(build_status_text), reply_markup=status_keyboard())


@router.message(Command("processes"))
async def processes_handler(message: Message) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        await deny_message(message)
        return
    await message.answer(await asyncio.to_thread(build_processes_text))


@router.message(Command("network"))
async def network_handler(message: Message) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        await deny_message(message)
        return
    await message.answer(await asyncio.to_thread(build_network_text))


@router.callback_query(F.data == "refresh_status")
async def refresh_status(callback: CallbackQuery) -> None:
    if await deny_callback(callback):
        return
    await callback.answer("Updating…")
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(
            await asyncio.to_thread(build_status_text), reply_markup=status_keyboard()
        )
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error).lower():
            logger.warning("Could not update status: %s", error)


@router.callback_query(F.data == "main_menu")
async def main_menu(callback: CallbackQuery) -> None:
    if await deny_callback(callback):
        return
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(main_menu_text(), reply_markup=menu_keyboard())
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error).lower():
            logger.warning("Could not show main menu: %s", error)


async def monitoring_loop(bot: Bot) -> None:
    while True:
        try:
            cpu = await asyncio.to_thread(psutil.cpu_percent, 5)
            memory = psutil.virtual_memory().percent
            temperature = await asyncio.to_thread(get_cpu_temperature)
            metrics = (
                ("cpu", cpu > CPU_ALERT_THRESHOLD, f"⚠️ High CPU usage: {cpu:.0f}%"),
                ("memory", memory > MEMORY_ALERT_THRESHOLD, f"⚠️ High memory usage: {memory:.0f}%"),
                ("temperature", temperature is not None and temperature > TEMP_ALERT_THRESHOLD,
                 f"🌡 High CPU temperature: {temperature:.1f}°C" if temperature is not None else ""),
            )
            for key, is_high, text in metrics:
                high_sample_count[key] = high_sample_count[key] + 1 if is_high else 0
                last_alert = last_alert_time.get(key)
                can_alert = not last_alert or datetime.now() - last_alert > timedelta(minutes=ALERT_COOLDOWN_MINUTES)
                if high_sample_count[key] >= CONSECUTIVE_HIGH_SAMPLES and can_alert:
                    await bot.send_message(OWNER_ID, text)
                    last_alert_time[key] = datetime.now()
        except Exception:
            logger.exception("Monitoring loop failed")
        await asyncio.sleep(MONITORING_INTERVAL_SECONDS)


async def main() -> None:
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    monitor_task = asyncio.create_task(monitoring_loop(bot), name="system-monitor")
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        monitor_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
