import html
import json
import logging
import subprocess
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps

import psutil
import telebot
from telebot import types

import app.config as config


OWNER_ID = 5656325153
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
    raise RuntimeError("BOT_TOKEN is not configured")

bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode=None)
last_alert_time: dict[str, datetime] = {}
high_sample_count: defaultdict[str, int] = defaultdict(int)
alert_lock = threading.Lock()


def owner_only(func):
    """Allow handlers to be called only by the configured Telegram user."""
    @wraps(func)
    def wrapper(message_or_call, *args, **kwargs):
        user = getattr(message_or_call, "from_user", None)
        message = getattr(message_or_call, "message", message_or_call)
        chat_id = getattr(getattr(message, "chat", None), "id", None)

        if user is None or user.id != OWNER_ID:
            if chat_id is not None:
                bot.send_message(chat_id, "⛔ Access denied.")
            return None
        return func(message_or_call, *args, **kwargs)

    return wrapper


def format_uptime() -> str:
    total_seconds = int(time.time() - psutil.boot_time())
    days, remainder = divmod(total_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, _ = divmod(remainder, 60)
    parts = ([f"{days}d"] if days else []) + ([f"{hours}h"] if hours else [])
    return " ".join([*parts, f"{minutes}m"])


def get_cpu_temperature() -> float | None:
    """Return the CPU temperature from iSMC on macOS, if available."""
    try:
        result = subprocess.run(
            ["ismc", "temp", "-o", "json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        sensors = json.loads(result.stdout)
        die_average = sensors.get("CPU Die Average", {}).get("quantity")
        if isinstance(die_average, (int, float)):
            return float(die_average)

        temperatures = [
            value["quantity"]
            for name, value in sensors.items()
            if "cpu" in name.lower() and isinstance(value, dict)
            and isinstance(value.get("quantity"), (int, float))
        ]
        return sum(temperatures) / len(temperatures) if temperatures else None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired,
            json.JSONDecodeError, TypeError) as exc:
        logger.debug("Could not read CPU temperature: %s", exc)
        return None


def get_top_processes(limit: int = 8) -> list[dict]:
    """Sample CPU use once, then return the busiest accessible processes."""
    processes = []
    for process in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            process.cpu_percent(None)  # establish the first measurement
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
                "memory_percent": process.memory_percent(),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(result, key=lambda item: item["cpu_percent"], reverse=True)[:limit]


def build_processes_text() -> str:
    lines = ["🔥 <b>Top processes (CPU)</b>", "<pre>"]
    for process in get_top_processes():
        name = html.escape((process["name"] or "unknown")[:22])
        lines.append(f"{name:<22} PID {process['pid']:<7} {process['cpu_percent']:>5.1f}%")
    return "\n".join([*lines, "</pre>"])


def build_network_text(sample_seconds: float = 1.0) -> str:
    start = psutil.net_io_counters()
    time.sleep(sample_seconds)
    end = psutil.net_io_counters()
    sent_speed = (end.bytes_sent - start.bytes_sent) / 1024 / sample_seconds
    received_speed = (end.bytes_recv - start.bytes_recv) / 1024 / sample_seconds
    return "\n".join([
        "🌐 <b>Network</b>", "",
        f"⬆ Upload:   {sent_speed:.1f} KB/s",
        f"⬇ Download: {received_speed:.1f} KB/s", "",
        f"Total sent:     {end.bytes_sent // (1024**2)} MB",
        f"Total received: {end.bytes_recv // (1024**2)} MB",
    ])


def bar(percent: float, length: int = 10) -> str:
    filled = max(0, min(length, round(percent / 100 * length)))
    return "█" * filled + "░" * (length - filled)


def build_status_text() -> str:
    cpu = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
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
        state = "🔌 charging" if battery.power_plugged else "🔋 on battery"
        lines.append(f"🔋 Battery: {battery.percent:.0f}% ({state})")
    return "\n".join([*lines, "", f"<i>Updated: {datetime.now():%H:%M:%S}</i>"])


def status_keyboard() -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔄 Refresh", callback_data="refresh_status"))
    keyboard.add(types.InlineKeyboardButton("🏠 Main menu", callback_data="main_menu"))
    return keyboard


def main_menu_text() -> str:
    return (
        "🖥 <b>System Monitor Bot</b>\n\n"
        "/status — CPU, memory, disk, temperature, battery\n"
        "/processes — top processes by CPU use\n"
        "/network — current upload/download speed\n\n"
        "You will receive an alert when a metric stays above its threshold."
    )


@bot.message_handler(commands=["start", "help"])
@owner_only
def send_welcome(message):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📊 Check status", callback_data="refresh_status"))
    bot.send_message(message.chat.id, main_menu_text(), parse_mode="HTML", reply_markup=keyboard)


@bot.message_handler(commands=["status"])
@owner_only
def status_command(message):
    bot.send_message(message.chat.id, build_status_text(), parse_mode="HTML", reply_markup=status_keyboard())


@bot.message_handler(commands=["processes"])
@owner_only
def processes_command(message):
    bot.send_message(message.chat.id, build_processes_text(), parse_mode="HTML")


@bot.message_handler(commands=["network"])
@owner_only
def network_command(message):
    bot.send_message(message.chat.id, build_network_text(), parse_mode="HTML")


@bot.callback_query_handler(func=lambda call: call.data == "refresh_status")
@owner_only
def refresh_status(call):
    bot.answer_callback_query(call.id, "Updating…")
    try:
        bot.edit_message_text(build_status_text(), call.message.chat.id, call.message.message_id,
                              parse_mode="HTML", reply_markup=status_keyboard())
    except telebot.apihelper.ApiTelegramException as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Could not update status message: %s", exc)


@bot.callback_query_handler(func=lambda call: call.data == "main_menu")
@owner_only
def main_menu(call):
    bot.answer_callback_query(call.id)
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📊 Check status", callback_data="refresh_status"))
    try:
        bot.edit_message_text(main_menu_text(), call.message.chat.id, call.message.message_id,
                              parse_mode="HTML", reply_markup=keyboard)
    except telebot.apihelper.ApiTelegramException as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Could not show main menu: %s", exc)


def ready_to_alert(key: str, is_high: bool) -> bool:
    """Alert after sustained high readings, with a thread-safe cooldown."""
    with alert_lock:
        high_sample_count[key] = high_sample_count[key] + 1 if is_high else 0
        if high_sample_count[key] < CONSECUTIVE_HIGH_SAMPLES:
            return False
        now = datetime.now()
        previous = last_alert_time.get(key)
        if previous and now - previous <= timedelta(minutes=ALERT_COOLDOWN_MINUTES):
            return False
        last_alert_time[key] = now
        return True


def monitoring_loop():
    while True:
        try:
            cpu = psutil.cpu_percent(interval=5)
            memory = psutil.virtual_memory().percent
            temperature = get_cpu_temperature()
            alerts = (
                ("cpu", cpu > CPU_ALERT_THRESHOLD, f"⚠️ High CPU usage: {cpu:.0f}%"),
                ("memory", memory > MEMORY_ALERT_THRESHOLD, f"⚠️ High memory usage: {memory:.0f}%"),
                ("temperature", temperature is not None and temperature > TEMP_ALERT_THRESHOLD,
                 f"🌡 High CPU temperature: {temperature:.1f}°C" if temperature is not None else ""),
            )
            for key, is_high, text in alerts:
                if ready_to_alert(key, is_high):
                    bot.send_message(OWNER_ID, text)
        except Exception:
            logger.exception("Monitoring loop failed")
        time.sleep(MONITORING_INTERVAL_SECONDS)


def main():
    threading.Thread(target=monitoring_loop, name="system-monitor", daemon=True).start()
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except Exception:
            logger.exception("Polling crashed; retrying in 5 seconds")
            time.sleep(5)


if __name__ == "__main__":
    main()
