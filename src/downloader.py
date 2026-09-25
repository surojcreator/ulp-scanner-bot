"""File downloader supporting both aiogram 3 Bot API and Telethon MTProto."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Optional

from aiogram import Bot
from aiogram.types import Document

from src.config import (
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    TELEGRAM_SESSION_NAME,
)

logger = logging.getLogger(__name__)

# Optional Telethon client reference
_telethon_client = None


async def get_telethon_client():
    """Initializes or returns the Telethon MTProto client if credentials exist."""
    global _telethon_client
    if _telethon_client is not None:
        return _telethon_client

    if TELEGRAM_API_ID and TELEGRAM_API_HASH:
        try:
            from telethon import TelegramClient

            client = TelegramClient(TELEGRAM_SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                _telethon_client = client
                logger.info("Telethon MTProto client connected and authorized.")
                return _telethon_client
            else:
                logger.warning("Telethon client connected but not authorized. Log in via session script if needed.")
        except Exception as e:
            logger.warning(f"Could not initialize Telethon client: {e}")

    return None


async def download_telegram_document(
    bot: Bot,
    document: Document,
    destination: Path,
    message=None,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> Path:
    """Downloads a Telegram document.
    
    Tries Bot API first. If file is >20MB and standard Bot API fails,
    falls back to Telethon MTProto client if configured.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_size = document.file_size or 0

    # 1. Standard Bot API download
    # Note: Bot API public server limits downloads to 20MB; local Bot API server supports up to 2GB.
    if file_size <= 20 * 1024 * 1024 or bot.session.api.is_local:
        try:
            tg_file = await bot.get_file(document.file_id)
            if tg_file.file_path:
                await bot.download_file(tg_file.file_path, destination)
                return destination
        except Exception as e:
            logger.info(f"Bot API get_file failed or exceeded limits: {e}. Trying MTProto fallback...")

    # 2. Telethon MTProto client fallback for files >20MB
    client = await get_telethon_client()
    if client and message is not None:
        try:
            last_edit = [time.time()]

            def _telethon_progress(current, total):
                if progress_callback:
                    progress_callback(current, total)

            # Download using Telethon from the message object
            await client.download_media(
                message.message_id,
                file=destination,
                progress_callback=_telethon_progress
            )
            return destination
        except Exception as e:
            logger.error(f"Telethon download failed: {e}")
            raise

    # 3. Final attempt with bot.download
    try:
        tg_file = await bot.get_file(document.file_id)
        if tg_file.file_path:
            await bot.download_file(tg_file.file_path, destination)
            return destination
    except Exception as e:
        raise RuntimeError(
            f"Unable to download file ({file_size / (1024*1024):.1f} MB). "
            f"Telegram Bot API limits public downloads to 20 MB. "
            f"To download larger files, configure TELEGRAM_API_SERVER (local Bot API) "
            f"or TELEGRAM_API_ID/HASH (Telethon client) in .env. Original error: {e}"
        ) from e

    return destination
