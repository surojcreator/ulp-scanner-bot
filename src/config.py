"""Configuration and environment variables loader.
Adheres to skill-tg guidelines.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Base workspace directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

# Telegram Bot configuration
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
TELEGRAM_API_SERVER: str | None = os.getenv("TELEGRAM_API_SERVER", "").strip() or None
PREMIUM_EMOJI: bool = os.getenv("PREMIUM_EMOJI", "off").lower() in ("on", "true", "1")

# Telethon MTProto Client configuration (enables >20MB downloads up to 2GB)
TELEGRAM_API_ID_RAW = os.getenv("TELEGRAM_API_ID", "").strip()
TELEGRAM_API_ID: int | None = int(TELEGRAM_API_ID_RAW) if TELEGRAM_API_ID_RAW.isdigit() else None
TELEGRAM_API_HASH: str | None = os.getenv("TELEGRAM_API_HASH", "").strip() or None
TELEGRAM_SESSION_NAME: str = os.getenv("TELEGRAM_SESSION_NAME", "ulp_userbot").strip()

# Storage directories
DATA_DIR: Path = BASE_DIR / os.getenv("DATA_DIR", "data")
INCOMING_DIR: Path = DATA_DIR / "incoming"
OUTPUT_DIR: Path = DATA_DIR / "output"
TEMP_DIR: Path = DATA_DIR / "temp"

# Processing parameters
MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "2048"))
CHUNK_SIZE_LINES: int = int(os.getenv("CHUNK_SIZE_LINES", "500000"))

# Ensure base directories exist
for directory in (DATA_DIR, INCOMING_DIR, OUTPUT_DIR, TEMP_DIR):
    directory.mkdir(parents=True, exist_ok=True)
