"""Telegram Bot handlers and interaction logic using aiogram 3."""

from __future__ import annotations

import html
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    Message,
)

from src.config import (
    BOT_TOKEN,
    TELEGRAM_API_SERVER,
)
from src.downloader import download_telegram_document
from src.keyboards import (
    confirm_clear_keyboard,
    processing_done_keyboard,
    queue_control_keyboard,
)
from src.processor import ProcessingReport, processor
from src.storage import QueuedFile, storage_manager

logger = logging.getLogger(__name__)

router = Router(name="ulp_bot_router")

# Cache last processing report per chat for on-demand downloads
_last_reports: dict[int, ProcessingReport] = {}


# ---------------------------------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    text = (
        "👋 <b>Welcome to the ULP Merger & Cleaner Bot!</b>\n\n"
        "I can store your forwarded files and process big <code>url:user:password</code> dumps:\n"
        "1. 📥 <b>Store files:</b> Forward or upload any text/zip dumps to build a processing queue.\n"
        "2. ⚡ <b>Merge & Deduplicate:</b> Streamlines all files into one consolidated list and removes duplicates.\n"
        "3. 🗑 <b>Clean Server Disk:</b> Deletes the original forwarded files immediately once merged.\n"
        "4. 🔍 <b>Error Checking:</b> Validates every record for correct <code>url:user:password</code> syntax and flags errors.\n\n"
        "👉 <i>Simply forward or drag-and-drop your files here to get started!</i>"
    )
    count, _, _ = storage_manager.get_queue_stats(message.chat.id)
    await message.answer(text, reply_markup=queue_control_keyboard(count))


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    text = (
        "📖 <b>How to use ULP Cleaner Bot:</b>\n\n"
        "• <b>Forward files:</b> Send or forward <code>.txt</code>, <code>.csv</code>, <code>.log</code>, or <code>.zip</code> files.\n"
        "• <b>/files:</b> View all files currently stored in your processing queue.\n"
        "• <b>/merge:</b> Merge all queued files, remove duplicates, delete original files, and validate.\n"
        "• <b>/clear:</b> Delete all queued files from the server without processing.\n\n"
        "<b>Format checked:</b> <code>url:user:password</code>\n"
        "• Supports colon (<code>:</code>), pipe (<code>|</code>), semicolon (<code>;</code>), or tab (<code>\\t</code>).\n"
        "• Handles URLs with ports (e.g. <code>http://site.com:8080</code>) and complex passwords containing colons."
    )
    await message.answer(text)


@router.message(Command("files"))
@router.message(Command("queue"))
async def handle_queue(message: Message) -> None:
    chat_id = message.chat.id
    files = storage_manager.get_queued_files(chat_id)
    count, _, human_size = storage_manager.get_queue_stats(chat_id)

    if not files:
        await message.answer(
            "📭 <b>Your queue is empty.</b>\nForward or send files here to add them to storage.",
            reply_markup=queue_control_keyboard(0)
        )
        return

    file_lines = []
    for idx, f in enumerate(files[:15], 1):
        safe_name = html.escape(f.original_name)
        file_lines.append(f"{idx}. 📄 <b>{safe_name}</b> ({f.human_size})")

    if len(files) > 15:
        file_lines.append(f"<i>...and {len(files) - 15} more files</i>")

    text = (
        f"📋 <b>Stored Files in Queue ({count} files, {human_size}):</b>\n\n"
        + "\n".join(file_lines)
        + "\n\n<i>Click below to merge, deduplicate, and check for errors.</i>"
    )
    await message.answer(text, reply_markup=queue_control_keyboard(count))


@router.message(Command("clear"))
async def handle_clear_command(message: Message) -> None:
    count, _, human_size = storage_manager.get_queue_stats(message.chat.id)
    if count == 0:
        await message.answer("📭 Queue is already empty.")
        return
    await message.answer(
        f"⚠️ Are you sure you want to delete all <b>{count} files</b> ({human_size}) from the server?",
        reply_markup=confirm_clear_keyboard()
    )


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

    status_msg = await message.reply("⏳ <i>Receiving and storing file on server...</i>")

    try:
        # Determine local destination path
        safe_uuid = uuid.uuid4().hex[:8]
        safe_stem = Path(raw_filename).stem.replace(" ", "_")
        safe_suffix = Path(raw_filename).suffix or ".txt"
        dest_filename = f"{safe_uuid}_{safe_stem}{safe_suffix}"
        
        chat_dir = storage_manager.get_chat_incoming_dir(chat_id)
        dest_path = chat_dir / dest_filename

        # Download file
        await download_telegram_document(
            bot=bot,
            document=doc,
            destination=dest_path,
            message=message
        )

        actual_size = dest_path.stat().st_size if dest_path.exists() else file_size

        # Register in storage manager
        storage_manager.add_queued_file(
            chat_id=chat_id,
            path=dest_path,
            original_name=raw_filename,
            size_bytes=actual_size,
            file_id=doc.file_id
        )

        total_count, _, total_human_size = storage_manager.get_queue_stats(chat_id)
        safe_name_display = html.escape(raw_filename)

        reply_text = (
            f"✅ <b>File Stored in Queue!</b>\n\n"
            f"📄 <b>File:</b> <code>{safe_name_display}</code>\n"
            f"📦 <b>Size:</b> <code>{_format_bytes(actual_size)}</code>\n\n"
            f"📊 <b>Total Queue:</b> {total_count} file(s) ({total_human_size})\n\n"
            f"<i>Forward more files or click <b>Merge & Clean</b> below!</i>"
        )
        await status_msg.edit_text(reply_text, reply_markup=queue_control_keyboard(total_count))

    except Exception as e:
        logger.error(f"Error downloading document: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ <b>Failed to store file:</b>\n<code>{html.escape(str(e))}</code>"
        )


# ---------------------------------------------------------------------------
# PROCESSING WORKFLOW: MERGE -> DEDUPLICATE -> DELETE SOURCES -> CHECK ERRORS
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
        text = "📭 <b>No files in queue to merge!</b>\nPlease forward or send some files first."
        if isinstance(event, CallbackQuery):
            await reply_to_msg.edit_text(text, reply_markup=queue_control_keyboard(0))
        else:
            await reply_to_msg.answer(text, reply_markup=queue_control_keyboard(0))
        return

    progress_msg = await reply_to_msg.answer("🚀 <i>Starting merge and deduplication pipeline...</i>")
    last_update = [time.time()]

    async def _async_progress(text: str):
        now = time.time()
        if now - last_update[0] >= 1.5:
            last_update[0] = now
            try:
                await progress_msg.edit_text(f"⏳ <i>{html.escape(text)}</i>")
            except Exception:
                pass

    def _sync_progress(text: str):
        # Called from sync thread/processor
        pass

    try:
        await progress_msg.edit_text("🔄 <i>Step 1/3: Merging files and deduplicating lines...</i>")
        
        # Run processing
        report = processor.process(chat_id, files, progress_callback=_sync_progress)
        _last_reports[chat_id] = report

        # Build clean HTML summary report
        error_summary_lines = []
        if report.error_breakdown:
            error_summary_lines.append("\n<b>Top Errors Detected:</b>")
            for err_code, count in sorted(report.error_breakdown.items(), key=lambda x: x[1], reverse=True)[:5]:
                error_summary_lines.append(f"  • <code>{err_code}</code>: <b>{count:,}</b> lines")

        report_text = (
            "🎉 <b>Merge & Error-Check Complete!</b>\n\n"
            f"📁 <b>Source Files Merged:</b> {report.total_files}\n"
            f"🗑 <b>Original Files Deleted:</b> {report.source_files_deleted} (Disk space freed!)\n"
            f"📄 <b>Total Raw Lines:</b> {report.total_raw_lines:,}\n"
            f"✨ <b>Unique Lines:</b> {report.unique_lines:,} "
            f"(📉 <b>{report.duplicates_dropped:,}</b> duplicates removed)\n"
            f"✅ <b>Valid ULP Records:</b> <b>{report.valid_lines:,}</b>\n"
            f"⚠️ <b>Syntax/Format Errors:</b> <b>{report.error_lines:,}</b>\n"
            f"⏱ <b>Processing Time:</b> {report.duration_seconds:.2f}s\n"
            + "\n".join(error_summary_lines)
        )

        has_clean = report.clean_file_path is not None and report.clean_file_path.exists()
        has_errors = report.error_file_path is not None and report.error_file_path.exists()

        await progress_msg.edit_text(
            report_text,
            reply_markup=processing_done_keyboard(has_clean, has_errors)
        )

        # Automatically send the clean file if <= 50MB (Telegram bot document upload cap)
        if has_clean and report.clean_file_size <= 50 * 1024 * 1024:
            clean_input = FSInputFile(
                path=report.clean_file_path,
                filename=f"clean_ulp_{int(time.time())}.txt"
            )
            await reply_to_msg.answer_document(
                document=clean_input,
                caption=f"✅ <b>Cleaned ULP File</b> ({report.valid_lines:,} lines, {report.human_clean_size})"
            )
        elif has_clean:
            await reply_to_msg.answer(
                f"ℹ️ <b>Clean file is large ({report.human_clean_size}).</b>\n"
                f"Saved on server at:\n<code>{html.escape(str(report.clean_file_path))}</code>"
            )

        # If there were errors, send the error file as well so the user can inspect
        if has_errors and report.error_file_size <= 50 * 1024 * 1024:
            err_input = FSInputFile(
                path=report.error_file_path,
                filename=f"errors_ulp_{int(time.time())}.txt"
            )
            await reply_to_msg.answer_document(
                document=err_input,
                caption=f"⚠️ <b>Errors Log</b> ({report.error_lines:,} lines that failed validation, {report.human_error_size})"
            )

    except Exception as e:
        logger.error(f"Error during processing: {e}", exc_info=True)
        await progress_msg.edit_text(
            f"❌ <b>Processing error:</b>\n<code>{html.escape(str(e))}</code>"
        )


# ---------------------------------------------------------------------------
# CALLBACK ACTIONS
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "action_list")
async def callback_list(query: CallbackQuery) -> None:
    chat_id = query.message.chat.id
    await query.answer()
    files = storage_manager.get_queued_files(chat_id)
    count, _, human_size = storage_manager.get_queue_stats(chat_id)

    if not files:
        await query.message.edit_text(
            "📭 <b>Queue is empty.</b>",
            reply_markup=queue_control_keyboard(0)
        )
        return

    file_lines = []
    for idx, f in enumerate(files[:15], 1):
        file_lines.append(f"{idx}. 📄 <b>{html.escape(f.original_name)}</b> ({f.human_size})")

    text = (
        f"📋 <b>Stored Files in Queue ({count} files, {human_size}):</b>\n\n"
        + "\n".join(file_lines)
    )
    await query.message.edit_text(text, reply_markup=queue_control_keyboard(count))


@router.callback_query(F.data == "action_clear")
async def callback_clear_ask(query: CallbackQuery) -> None:
    chat_id = query.message.chat.id
    count, _, human_size = storage_manager.get_queue_stats(chat_id)
    await query.answer()
    if count == 0:
        await query.message.edit_text("📭 Queue is already empty.", reply_markup=queue_control_keyboard(0))
        return

    await query.message.edit_text(
        f"⚠️ <b>Delete all {count} files ({human_size}) from the queue and server?</b>",
        reply_markup=confirm_clear_keyboard()
    )


@router.callback_query(F.data == "confirm_clear")
async def callback_confirm_clear(query: CallbackQuery) -> None:
    chat_id = query.message.chat.id
    deleted = storage_manager.clear_queue(chat_id)
    await query.answer(f"Deleted {deleted} files.")
    await query.message.edit_text(
        "🗑 <b>Queue cleared and source files deleted from server.</b>",
        reply_markup=queue_control_keyboard(0)
    )


@router.callback_query(F.data == "cancel_clear")
async def callback_cancel_clear(query: CallbackQuery) -> None:
    chat_id = query.message.chat.id
    count, _, _ = storage_manager.get_queue_stats(chat_id)
    await query.answer("Cancelled.")
    await query.message.edit_text(
        "Action cancelled. Files remain safely in queue.",
        reply_markup=queue_control_keyboard(count)
    )


@router.callback_query(F.data == "action_help")
async def callback_help(query: CallbackQuery) -> None:
    await query.answer()
    await query.message.reply(
        "Forward or upload any <code>.txt</code> or <code>.zip</code> files directly to this chat.\n"
        "They will be stored on the server ready for merging and error checking!"
    )


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
    """Creates configured Bot instance."""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is missing! Set it in your .env file.")

    default_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
    
    # If self-hosted Bot API server is configured, use it for unlimited downloads/2GB uploads
    if TELEGRAM_API_SERVER:
        from aiogram.client.session.aiohttp import AiohttpSession
        from aiogram.client.telegram import TelegramAPIServer

        server = TelegramAPIServer.from_base(TELEGRAM_API_SERVER, is_local=True)
        session = AiohttpSession(api=server)
        return Bot(token=BOT_TOKEN, session=session, default=default_props)

    return Bot(token=BOT_TOKEN, default=default_props)


def create_dispatcher() -> Dispatcher:
    """Creates configured Dispatcher with registered routers."""
    dp = Dispatcher()
    dp.include_router(router)
    return dp


def _format_bytes(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"
