"""Telegram Bot handlers and interaction logic using aiogram 3.
Engineered according to skill-tg best practices and screen design bar.
"""

from __future__ import annotations

import html
import logging
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    Message,
)

import src.config as config
import src.keyboards as k
import src.texts as texts
from src.downloader import download_telegram_document
from src.emoji_map import premiumize
from src.processor import ProcessingReport, processor
from src.storage import QueuedFile, storage_manager

logger = logging.getLogger(__name__)

router = Router(name="ulp_bot_router")

# Cache last processing report per chat for on-demand downloads
_last_reports: Dict[int, ProcessingReport] = {}


# ---------------------------------------------------------------------------
# RENDER PIPELINE (skill-tg standard)
# ---------------------------------------------------------------------------

def render(template: str, **values) -> str:
    """Renders a trusted HTML template by escaping ONLY dynamic interpolated values,
    then applying premium custom emoji substitution if enabled.
    """
    safe_values = {key: html.escape(str(val)) for key, val in values.items()}
    formatted = template.format(**safe_values)
    return premiumize(formatted, config.PREMIUM_EMOJI)


def _format_bytes(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


# ---------------------------------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    chat_id = message.chat.id
    count, _, human_size = storage_manager.get_queue_stats(chat_id)
    text = render(texts.START_TEXT, count=count, size=human_size)
    await message.answer(text, reply_markup=k.queue_keyboard(count))


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    text = render(texts.HELP_TEXT)
    await message.answer(text, reply_markup=k.back_to_home_keyboard())


@router.message(Command("files"))
@router.message(Command("queue"))
async def handle_queue(message: Message) -> None:
    chat_id = message.chat.id
    files = storage_manager.get_queued_files(chat_id)
    count, _, human_size = storage_manager.get_queue_stats(chat_id)

    if not files:
        text = render(texts.QUEUE_EMPTY_TEXT)
        await message.answer(text, reply_markup=k.queue_keyboard(0))
        return

    file_items = "\n".join(
        f"• 📄 <b>{html.escape(f.original_name)}</b> (<code>{f.human_size}</code>)"
        for f in files[:20]
    )
    if len(files) > 20:
        file_items += f"\n<i>...and {len(files) - 20} more files</i>"

    # Notice: file_items contains internal trusted markup, so we format directly
    text = texts.QUEUE_LIST_TEXT.format(
        count=html.escape(str(count)),
        total_size=html.escape(human_size),
        file_items=file_items
    )
    await message.answer(premiumize(text, config.PREMIUM_EMOJI), reply_markup=k.queue_list_keyboard())


@router.message(Command("clear"))
async def handle_clear_command(message: Message) -> None:
    chat_id = message.chat.id
    count, _, human_size = storage_manager.get_queue_stats(chat_id)
    if count == 0:
        await message.answer(render(texts.QUEUE_EMPTY_TEXT), reply_markup=k.queue_keyboard(0))
        return

    text = render(texts.CONFIRM_CLEAR_TEXT, count=count, total_size=human_size)
    await message.answer(text, reply_markup=k.confirm_clear_keyboard())


# ---------------------------------------------------------------------------
# DOCUMENT INGESTION (FORWARDED OR UPLOADED FILES)
# ---------------------------------------------------------------------------

@router.message(F.document)
async def handle_incoming_document(message: Message, bot: Bot) -> None:
    doc = message.document
    if not doc:
        return

    chat_id = message.chat.id
    raw_filename = doc.file_name or f"unnamed_{int(time.time())}.txt"
    file_size = doc.file_size or 0

    status_msg = await message.reply("⏳ <i>Receiving file and caching to server storage...</i>")

    try:
        safe_uuid = uuid.uuid4().hex[:8]
        safe_stem = Path(raw_filename).stem.replace(" ", "_")
        safe_suffix = Path(raw_filename).suffix or ".txt"
        dest_filename = f"{safe_uuid}_{safe_stem}{safe_suffix}"

        chat_dir = storage_manager.get_chat_incoming_dir(chat_id)
        dest_path = chat_dir / dest_filename

        await download_telegram_document(
            bot=bot,
            document=doc,
            destination=dest_path,
            message=message
        )

        actual_size = dest_path.stat().st_size if dest_path.exists() else file_size

        storage_manager.add_queued_file(
            chat_id=chat_id,
            path=dest_path,
            original_name=raw_filename,
            size_bytes=actual_size,
            file_id=doc.file_id
        )

        total_count, _, total_human_size = storage_manager.get_queue_stats(chat_id)

        reply_text = render(
            texts.FILE_STORED_TEXT,
            filename=raw_filename,
            size=_format_bytes(actual_size),
            count=total_count,
            total_size=total_human_size
        )
        await status_msg.edit_text(reply_text, reply_markup=k.queue_keyboard(total_count))

    except Exception as e:
        logger.error(f"Error downloading document: {e}", exc_info=True)
        err_text = render(texts.ERROR_TEXT, error_message=str(e))
        await status_msg.edit_text(err_text, reply_markup=k.back_to_home_keyboard())


# ---------------------------------------------------------------------------
# PIPELINE: MERGE -> DEDUPLICATE -> DELETE SOURCES -> VALIDATE ERRORS
# ---------------------------------------------------------------------------

@router.message(Command("merge"))
@router.message(Command("clean"))
@router.callback_query(F.data == "action_merge")
async def trigger_merge_pipeline(event: Message | CallbackQuery, bot: Bot) -> None:
    if isinstance(event, CallbackQuery):
        chat_id = event.message.chat.id
        await event.answer()
        reply_to_msg = event.message
    else:
        chat_id = event.chat.id
        reply_to_msg = event

    files = storage_manager.get_queued_files(chat_id)
    if not files:
        empty_text = render(texts.QUEUE_EMPTY_TEXT)
        if isinstance(event, CallbackQuery):
            await reply_to_msg.edit_text(empty_text, reply_markup=k.queue_keyboard(0))
        else:
            await reply_to_msg.answer(empty_text, reply_markup=k.queue_keyboard(0))
        return

    progress_msg = await reply_to_msg.answer(render(texts.PROCESS_START_TEXT))

    def _sync_progress(step_info: str):
        pass

    try:
        await progress_msg.edit_text(render(texts.PROCESS_MERGING_TEXT))

        # Run pipeline
        report = processor.process(chat_id, files, progress_callback=_sync_progress)
        _last_reports[chat_id] = report

        # Build error breakdown list for the expandable blockquote
        if report.error_breakdown:
            breakdown_lines = [
                f"• <code>{html.escape(code)}</code>: <b>{count:,}</b> lines"
                for code, count in sorted(report.error_breakdown.items(), key=lambda x: x[1], reverse=True)
            ]
            breakdown_str = "\n".join(breakdown_lines)
        else:
            breakdown_str = "<i>No syntax errors detected!</i>"

        report_markup = texts.PROCESS_REPORT_TEXT.format(
            total_files=html.escape(str(report.total_files)),
            deleted_files=html.escape(str(report.source_files_deleted)),
            raw_lines=html.escape(f"{report.total_raw_lines:,}"),
            unique_lines=html.escape(f"{report.unique_lines:,}"),
            duplicates_dropped=html.escape(f"{report.duplicates_dropped:,}"),
            valid_lines=html.escape(f"{report.valid_lines:,}"),
            error_lines=html.escape(f"{report.error_lines:,}"),
            duration=html.escape(f"{report.duration_seconds:.2f}"),
            error_breakdown=breakdown_str
        )

        has_clean = report.clean_file_path is not None and report.clean_file_path.exists()
        has_errors = report.error_file_path is not None and report.error_file_path.exists()

        await progress_msg.edit_text(
            premiumize(report_markup, config.PREMIUM_EMOJI),
            reply_markup=k.report_keyboard(has_clean, has_errors)
        )

        # Send cleaned document if <= 50MB
        if has_clean and report.clean_file_size <= 50 * 1024 * 1024:
            clean_input = FSInputFile(
                path=report.clean_file_path,
                filename=f"clean_ulp_{int(time.time())}.txt"
            )
            await reply_to_msg.answer_document(
                document=clean_input,
                caption=f"✅ <b>Cleaned ULP File</b> ({report.valid_lines:,} lines, {report.human_clean_size})"
            )

        # Send errors document if errors exist and <= 50MB
        if has_errors and report.error_file_size <= 50 * 1024 * 1024:
            err_input = FSInputFile(
                path=report.error_file_path,
                filename=f"errors_ulp_{int(time.time())}.txt"
            )
            await reply_to_msg.answer_document(
                document=err_input,
                caption=f"⚠️ <b>Errors Log</b> ({report.error_lines:,} invalid lines, {report.human_error_size})"
            )

    except Exception as e:
        logger.error(f"Error in merge pipeline: {e}", exc_info=True)
        err_text = render(texts.ERROR_TEXT, error_message=str(e))
        await progress_msg.edit_text(err_text, reply_markup=k.back_to_home_keyboard())


# ---------------------------------------------------------------------------
# NAVIGATION & CALLBACKS
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "action_home")
async def callback_home(query: CallbackQuery) -> None:
    chat_id = query.message.chat.id
    await query.answer()
    count, _, human_size = storage_manager.get_queue_stats(chat_id)
    text = render(texts.START_TEXT, count=count, size=human_size)
    await query.message.edit_text(text, reply_markup=k.queue_keyboard(count))


@router.callback_query(F.data == "action_help")
async def callback_help(query: CallbackQuery) -> None:
    await query.answer()
    text = render(texts.HELP_TEXT)
    await query.message.edit_text(text, reply_markup=k.back_to_home_keyboard())


@router.callback_query(F.data == "action_list")
async def callback_list(query: CallbackQuery) -> None:
    chat_id = query.message.chat.id
    await query.answer()
    files = storage_manager.get_queued_files(chat_id)
    count, _, human_size = storage_manager.get_queue_stats(chat_id)

    if not files:
        await query.message.edit_text(render(texts.QUEUE_EMPTY_TEXT), reply_markup=k.queue_keyboard(0))
        return

    file_items = "\n".join(
        f"• 📄 <b>{html.escape(f.original_name)}</b> (<code>{f.human_size}</code>)"
        for f in files[:20]
    )
    if len(files) > 20:
        file_items += f"\n<i>...and {len(files) - 20} more files</i>"

    text = texts.QUEUE_LIST_TEXT.format(
        count=html.escape(str(count)),
        total_size=html.escape(human_size),
        file_items=file_items
    )
    await query.message.edit_text(premiumize(text, config.PREMIUM_EMOJI), reply_markup=k.queue_list_keyboard())


@router.callback_query(F.data == "action_clear")
async def callback_clear_ask(query: CallbackQuery) -> None:
    chat_id = query.message.chat.id
    await query.answer()
    count, _, human_size = storage_manager.get_queue_stats(chat_id)
    if count == 0:
        await query.message.edit_text(render(texts.QUEUE_EMPTY_TEXT), reply_markup=k.queue_keyboard(0))
        return

    text = render(texts.CONFIRM_CLEAR_TEXT, count=count, total_size=human_size)
    await query.message.edit_text(text, reply_markup=k.confirm_clear_keyboard())


@router.callback_query(F.data == "confirm_clear")
async def callback_confirm_clear(query: CallbackQuery) -> None:
    chat_id = query.message.chat.id
    deleted = storage_manager.clear_queue(chat_id)
    await query.answer(f"Deleted {deleted} files.")
    text = render(texts.QUEUE_CLEARED_TEXT)
    await query.message.edit_text(text, reply_markup=k.queue_keyboard(0))


@router.callback_query(F.data == "cancel_clear")
async def callback_cancel_clear(query: CallbackQuery) -> None:
    chat_id = query.message.chat.id
    await query.answer("Cancelled.")
    count, _, human_size = storage_manager.get_queue_stats(chat_id)
    text = render(texts.START_TEXT, count=count, size=human_size)
    await query.message.edit_text(text, reply_markup=k.queue_keyboard(count))


@router.callback_query(F.data == "download_clean")
async def callback_download_clean(query: CallbackQuery) -> None:
    chat_id = query.message.chat.id
    report = _last_reports.get(chat_id)
    if not report or not report.clean_file_path or not report.clean_file_path.exists():
        await query.answer("Clean file not available.", show_alert=True)
        return
    await query.answer("Sending clean file...")
    doc = FSInputFile(report.clean_file_path, filename="cleaned_ulp.txt")
    await query.message.answer_document(doc, caption="✅ <b>Cleaned ULP File</b>")


@router.callback_query(F.data == "download_errors")
async def callback_download_errors(query: CallbackQuery) -> None:
    chat_id = query.message.chat.id
    report = _last_reports.get(chat_id)
    if not report or not report.error_file_path or not report.error_file_path.exists():
        await query.answer("Errors file not available.", show_alert=True)
        return
    await query.answer("Sending errors file...")
    doc = FSInputFile(report.error_file_path, filename="errors_ulp.txt")
    await query.message.answer_document(doc, caption="⚠️ <b>Errors Log</b>")


# ---------------------------------------------------------------------------
# INITIALIZATION
# ---------------------------------------------------------------------------

def create_bot() -> Bot:
    if not config.BOT_TOKEN:
        raise ValueError("BOT_TOKEN is missing! Set it in your .env file.")

    default_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
    
    if config.TELEGRAM_API_SERVER:
        from aiogram.client.session.aiohttp import AiohttpSession
        from aiogram.client.telegram import TelegramAPIServer

        server = TelegramAPIServer.from_base(config.TELEGRAM_API_SERVER, is_local=True)
        session = AiohttpSession(api=server)
        return Bot(token=config.BOT_TOKEN, session=session, default=default_props)

    return Bot(token=config.BOT_TOKEN, default=default_props)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp
