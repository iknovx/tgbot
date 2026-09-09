import html
import json
import platform
import subprocess
import time
from datetime import datetime
from pathlib import Path

import psutil


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