from dataclasses import dataclass
from typing import Callable

from app.config import settings
from app.metrics import build_network_text, build_processes_text, build_status_text


def build_settings_text() -> str:
    lines = [
        "⚙️ <b>Alert Settings</b>", "",
        f"CPU threshold:         {settings.cpu_alert:.0f}%",
        f"Memory threshold:      {settings.memory_alert:.0f}%",
        f"Temperature threshold: {settings.temp_alert:.0f}°C",
        f"Battery low threshold: {settings.battery_low:.0f}%",
        "",
        f"Consecutive samples needed: {settings.consecutive_high_samples}",
        f"Check interval:             {settings.monitoring_interval_seconds}s",
        f"Alert cooldown:             {settings.alert_cooldown_minutes} min",
        "",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class Screen:
    key: str
    title: str
    builder: Callable[[], str]


SCREENS: dict[str, Screen] = {
    "status": Screen("status", "📊 Status", build_status_text),
    "processes": Screen("processes", "🔥 Processes", build_processes_text),
    "network": Screen("network", "🌐 Network", build_network_text),
    "settings": Screen("settings", "⚙️ Settings", build_settings_text),
}