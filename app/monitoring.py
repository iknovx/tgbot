import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta

import psutil
from aiogram import Bot

from app.config import settings
from app.metrics import get_cpu_temperature

logger = logging.getLogger(__name__)

last_alert_time: dict[str, datetime] = {}
high_sample_count: defaultdict[str, int] = defaultdict(int)


async def monitoring_loop(bot: Bot) -> None:
    logger.info("System monitor started; interval: %ss", settings.monitoring_interval_seconds)
    try:
        while True:
            try:
                cpu = await asyncio.to_thread(psutil.cpu_percent, 1)
                memory = psutil.virtual_memory().percent
                temperature = await asyncio.to_thread(get_cpu_temperature)
                battery = psutil.sensors_battery()

                metrics = (
                    ("cpu", cpu >= settings.cpu_alert, f"⚠️ <b>High CPU usage</b>: {cpu:.0f}%"),
                    ("memory", memory >= settings.memory_alert, f"⚠️ <b>High memory usage</b>: {memory:.0f}%"),
                    ("temperature", temperature is not None and temperature >= settings.temp_alert,
                     f"🌡 <b>High CPU temperature</b>: {temperature:.1f}°C" if temperature is not None else ""),
                    ("battery", battery is not None and not battery.power_plugged and battery.percent <= settings.battery_low,
                     f"🔋 <b>Low battery</b>: {battery.percent:.0f}%" if battery is not None else ""),
                )

                for key, is_high, text in metrics:
                    high_sample_count[key] = high_sample_count[key] + 1 if is_high else 0
                    last_alert = last_alert_time.get(key)
                    can_alert = not last_alert or datetime.now() - last_alert >= timedelta(minutes=settings.alert_cooldown_minutes)

                    if high_sample_count[key] >= settings.consecutive_high_samples and can_alert:
                        await bot.send_message(settings.owner_id, text)
                        last_alert_time[key] = datetime.now()
                        logger.warning("Sent %s alert", key)
            except Exception:
                logger.exception("Monitoring sample failed")

            await asyncio.sleep(settings.monitoring_interval_seconds)
    except asyncio.CancelledError:
        logger.info("System monitor stopped")
        raise
