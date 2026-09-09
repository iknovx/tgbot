# System Monitor Bot

A private Telegram dashboard for one computer, built with Python and Aiogram.
It provides live status screens and sends alerts only to the configured owner.

## What it monitors

- CPU, memory, disk, uptime and CPU temperature
- battery state when it is available
- top CPU-consuming processes
- current upload and download speed
- automatic alerts for high CPU, memory, temperature and low battery

An alert is sent only after the configured number of consecutive high readings
and then respects a cooldown. This prevents repeated notifications from a
single short spike.

## Stack

Python · Aiogram 3 · psutil · Pydantic Settings · python-dotenv

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and add your Telegram bot token and
   numeric Telegram user ID. Do not commit `.env`.
4. Start the bot:

   ```bash
   python main.py
   ```

Use `/start` to open the dashboard. Available commands are `/status`,
`/processes`, `/network` and `/settings`.

## Configuration

Every threshold and interval can be changed in `.env`. The defaults are
intended as a starting point: CPU and memory at 85%, temperature at 90°C,
low battery at 20%, with two consecutive samples before an alert.
