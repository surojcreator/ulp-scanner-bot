"""Main application entry point.
Supports running as a standalone MTProto/aiogram worker, or with a lightweight
HTTP health check server for free hosting platforms (Render, Koyeb, Fly.io).
"""

from __future__ import annotations

import asyncio
import logging
import os
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

logger = logging.getLogger("ulp_bot")


async def start_health_server(port: int):
    """Starts a minimal aiohttp HTTP server for cloud platforms requiring an open port."""
    try:
        from aiohttp import web

        async def healthz(request):
            return web.json_response({"status": "ok", "service": "ulp-scanner-bot"})

        app = web.Application()
        app.router.add_get("/", healthz)
        app.router.add_get("/healthz", healthz)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"Health check HTTP server listening on port {port} (allows Free tier web hosting)")
        return runner
    except Exception as e:
        logger.warning(f"Could not start health check HTTP server: {e}")
        return None


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logger.info("Initializing ULP Merger & Error-Checker Bot...")

    if not BOT_TOKEN:
        logger.error("ERROR: BOT_TOKEN is missing! Set it in your .env file.")
        sys.exit(1)

    # If PORT is provided (Render, Koyeb, Fly.io, etc.), run background health server
    health_runner = None
    port_env = os.getenv("PORT")
    if port_env and port_env.isdigit():
        health_runner = await start_health_server(int(port_env))

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
            if health_runner:
                await health_runner.cleanup()
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
        if health_runner:
            await health_runner.cleanup()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
