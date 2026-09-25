"""Main application entry point."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import (
    BOT_TOKEN,
    DATA_DIR,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    TELEGRAM_API_SERVER,
    TELEGRAM_SESSION_NAME,
)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logger = logging.getLogger("ulp_bot")
    logger.info("Initializing ULP Merger & Error-Checker Bot...")

    if not BOT_TOKEN:
        logger.error("ERROR: BOT_TOKEN is missing! Set it in your .env file.")
        sys.exit(1)

    # If Telethon MTProto credentials are configured, use the high-speed MTProto engine (supports up to 2GB downloads)
    if TELEGRAM_API_ID and TELEGRAM_API_HASH:
        logger.info("Running high-performance MTProto Bot Engine (supports >20MB downloads up to 2GB)...")
        from telethon import TelegramClient
        from src.tele_bot import setup_telethon_bot

        session_path = str(DATA_DIR / TELEGRAM_SESSION_NAME)
        client = TelegramClient(session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)
        await client.start(bot_token=BOT_TOKEN)
        setup_telethon_bot(client)

        me = await client.get_me()
        logger.info(f"Bot connected successfully via MTProto as @{me.username} (ID: {me.id})")
        logger.info("Listening for forwarded big files and commands. Press Ctrl+C to stop.")

        try:
            await client.run_until_disconnected()
        finally:
            await client.disconnect()
            logger.info("Telethon bot disconnected.")
        return

    # Fallback to standard aiogram 3 engine
    logger.info("Running standard aiogram 3 Bot Engine...")
    from src.bot import create_bot, create_dispatcher

    bot = create_bot()
    dp = create_dispatcher()

    me = await bot.get_me()
    logger.info(f"Bot connected successfully as @{me.username} (ID: {me.id})")
    logger.info("Listening for forwarded files and messages. Press Ctrl+C to stop.")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
