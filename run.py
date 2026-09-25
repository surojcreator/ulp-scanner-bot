"""Main application entry point."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.bot import create_bot, create_dispatcher
from src.config import BOT_TOKEN, TELEGRAM_API_SERVER
from src.downloader import get_telethon_client


async def main() -> None:
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logger = logging.getLogger("ulp_bot")
    logger.info("Initializing ULP Merger & Error-Checker Bot...")

    if not BOT_TOKEN:
        logger.error(
            "ERROR: BOT_TOKEN is not configured! "
            "Please create a .env file with your BOT_TOKEN from @BotFather."
        )
        sys.exit(1)

    # Initialize bot and dispatcher
    bot = create_bot()
    dp = create_dispatcher()

    if TELEGRAM_API_SERVER:
        logger.info(f"Using custom Telegram Bot API Server: {TELEGRAM_API_SERVER}")
    else:
        logger.info("Using official Telegram Bot API (api.telegram.org)")

    # Attempt to initialize Telethon MTProto client if configured
    telethon_client = await get_telethon_client()
    if telethon_client:
        logger.info("Telethon MTProto client ready for high-speed >20MB downloads.")

    # Get bot info
    me = await bot.get_me()
    logger.info(f"Bot connected successfully as @{me.username} (ID: {me.id})")
    logger.info("Listening for forwarded files and messages. Press Ctrl+C to stop.")

    try:
        # Delete any pending webhook updates and start long-polling
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        logger.info("Shutting down bot session...")
        await bot.session.close()
        if telethon_client:
            await telethon_client.disconnect()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
