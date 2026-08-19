import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в .env")

if not OWNER_ID:
    raise RuntimeError("OWNER_ID не найден в .env")

OWNER_ID = int(OWNER_ID)