"""Telethon-based MTProto Bot implementation.
Supports handling and downloading files of ANY size up to 2GB (bypassing HTTP Bot API 20MB limit).
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from telethon import Button, TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename

from src.config import (
    BOT_TOKEN,
    DATA_DIR,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    TELEGRAM_SESSION_NAME,
)
from src.processor import ProcessingReport, processor
from src.storage import QueuedFile, storage_manager

logger = logging.getLogger(__name__)

# Cache last processing report per chat for on-demand downloads
_last_reports: Dict[int, ProcessingReport] = {}


def get_filename_from_document(doc) -> str:
    """Extracts the original filename from a Telethon document's attributes."""
    if not doc or not hasattr(doc, "attributes"):
        return f"unnamed_{int(time.time())}.txt"
    for attr in doc.attributes:
        if isinstance(attr, DocumentAttributeFilename):
            return attr.file_name
    return f"unnamed_{int(time.time())}.txt"


def _format_bytes(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


def get_queue_keyboard(count: int):
    """Builds inline keyboard for queue management."""
    buttons = []
    if count > 0:
        buttons.append([
            Button.inline(f"⚡ Merge & Clean Queue ({count} files)", b"action_merge")
        ])
        buttons.append([
            Button.inline("📋 View Queue List", b"action_list"),
            Button.inline("🗑 Clear Queue", b"action_clear")
        ])
    else:
        buttons.append([
            Button.inline("📥 Forward / Send Files", b"action_help")
        ])
    return buttons


def get_done_keyboard(has_clean: bool, has_errors: bool):
    """Builds inline keyboard after processing."""
    row = []
    if has_clean:
        row.append(Button.inline("📥 Download Clean ULP", b"download_clean"))
    if has_errors:
        row.append(Button.inline("⚠️ Download Errors Log", b"download_errors"))
    buttons = []
    if row:
        buttons.append(row)
    buttons.append([
        Button.inline("➕ Process More Files", b"action_help"),
        Button.inline("📋 View Queue", b"action_list")
    ])
    return buttons


def get_confirm_clear_keyboard():
    return [
        [
            Button.inline("✅ Yes, Delete All", b"confirm_clear"),
            Button.inline("❌ Cancel", b"cancel_clear")
        ]
    ]


def setup_telethon_bot(client: TelegramClient) -> None:
    """Registers all event handlers on the Telethon client."""

    @client.on(events.NewMessage(pattern=r"^/start$"))
    async def on_start(event):
        chat_id = event.chat_id
        count, _, _ = storage_manager.get_queue_stats(chat_id)
        text = (
            "👋 **Welcome to the ULP Merger & Cleaner Bot!**\n\n"
            "I can store your forwarded files and process big `url:user:password` dumps:\n"
            "1. 📥 **Store files:** Forward or upload any text/zip dumps (supports **big files up to 2GB**).\n"
            "2. ⚡ **Merge & Deduplicate:** Merges all queued files and removes duplicate lines.\n"
            "3. 🗑 **Clean Server Disk:** Deletes original files immediately to keep disk space clean.\n"
            "4. 🔍 **Error Checking:** Validates every record for correct `url:user:password` format and flags errors.\n\n"
            "👉 _Simply forward or drag-and-drop your files here to begin!_"
        )
        await event.respond(text, buttons=get_queue_keyboard(count))

    @client.on(events.NewMessage(pattern=r"^/help$"))
    async def on_help(event):
        text = (
            "📖 **How to use ULP Cleaner Bot:**\n\n"
            "• **Forward files:** Send or forward `.txt`, `.csv`, `.log`, or `.zip` files.\n"
            "• **/files:** View all files currently stored in your processing queue.\n"
            "• **/merge:** Merge all queued files, remove duplicates, delete original files, and validate.\n"
            "• **/clear:** Delete all queued files from the server without processing.\n\n"
            "**Format checked:** `url:user:password`\n"
            "• Supports colon (`:`), pipe (`|`), semicolon (`;`), or tab (`\\t`).\n"
            "• Handles URLs with ports (e.g. `http://site.com:8080`) and complex passwords containing colons."
        )
        await event.respond(text)

    @client.on(events.NewMessage(pattern=r"^/(files|queue)$"))
    async def on_files(event):
        chat_id = event.chat_id
        files = storage_manager.get_queued_files(chat_id)
        count, _, human_size = storage_manager.get_queue_stats(chat_id)

        if not files:
            await event.respond(
                "📭 **Your queue is empty.**\nForward or send files here to add them to storage.",
                buttons=get_queue_keyboard(0)
            )
            return

        file_lines = []
        for idx, f in enumerate(files[:15], 1):
            file_lines.append(f"{idx}. 📄 **{f.original_name}** ({f.human_size})")

        if len(files) > 15:
            file_lines.append(f"_...and {len(files) - 15} more files_")

        text = (
            f"📋 **Stored Files in Queue ({count} files, {human_size}):**\n\n"
            + "\n".join(file_lines)
            + "\n\n_Click below to merge, deduplicate, and check for errors._"
        )
        await event.respond(text, buttons=get_queue_keyboard(count))

    @client.on(events.NewMessage(pattern=r"^/clear$"))
    async def on_clear(event):
        chat_id = event.chat_id
        count, _, human_size = storage_manager.get_queue_stats(chat_id)
        if count == 0:
            await event.respond("📭 Queue is already empty.")
            return
        await event.respond(
            f"⚠️ Are you sure you want to delete all **{count} files** ({human_size}) from the server?",
            buttons=get_confirm_clear_keyboard()
        )

    @client.on(events.NewMessage(func=lambda e: bool(e.document)))
    async def on_document(event):
        doc = event.document
        chat_id = event.chat_id
        raw_filename = get_filename_from_document(doc)
        file_size = doc.size or 0

        status_msg = await event.reply("⏳ _Receiving and downloading file via MTProto..._")

        try:
            safe_uuid = uuid.uuid4().hex[:8]
            safe_stem = Path(raw_filename).stem.replace(" ", "_")
            safe_suffix = Path(raw_filename).suffix or ".txt"
            dest_filename = f"{safe_uuid}_{safe_stem}{safe_suffix}"

            chat_dir = storage_manager.get_chat_incoming_dir(chat_id)
            dest_path = chat_dir / dest_filename

            last_edit = [time.time()]

            async def _progress(current, total):
                now = time.time()
                if now - last_edit[0] >= 2.0:
                    last_edit[0] = now
                    pct = (current / total) * 100 if total > 0 else 0
                    try:
                        await status_msg.edit(
                            f"⏳ _Downloading {raw_filename}: {pct:.1f}% ({_format_bytes(current)} / {_format_bytes(total)})_"
                        )
                    except Exception:
                        pass

            # Download media through MTProto (up to 2GB with NO 20MB limit!)
            await event.download_media(file=str(dest_path), progress_callback=_progress)

            actual_size = dest_path.stat().st_size if dest_path.exists() else file_size

            # Register in storage manager
            storage_manager.add_queued_file(
                chat_id=chat_id,
                path=dest_path,
                original_name=raw_filename,
                size_bytes=actual_size,
                file_id=str(doc.id)
            )

            total_count, _, total_human_size = storage_manager.get_queue_stats(chat_id)

            reply_text = (
                f"✅ **File Stored in Queue!**\n\n"
                f"📄 **File:** `{raw_filename}`\n"
                f"📦 **Size:** `{_format_bytes(actual_size)}`\n\n"
                f"📊 **Total Queue:** {total_count} file(s) ({total_human_size})\n\n"
                f"_Forward more files or click **Merge & Clean** below!_"
            )
            await status_msg.edit(reply_text, buttons=get_queue_keyboard(total_count))

        except Exception as e:
            logger.error(f"Error downloading document: {e}", exc_info=True)
            await status_msg.edit(f"❌ **Failed to download file:**\n`{str(e)}`")

    @client.on(events.NewMessage(pattern=r"^/(merge|clean)$"))
    async def on_merge_command(event):
        await run_merge_pipeline(event.chat_id, event)

    @client.on(events.CallbackQuery(data=b"action_merge"))
    async def on_callback_merge(event):
        await event.answer()
        await run_merge_pipeline(event.chat_id, event)

    async def run_merge_pipeline(chat_id: int, event):
        files = storage_manager.get_queued_files(chat_id)
        if not files:
            text = "📭 **No files in queue to merge!**\nPlease forward or send some files first."
            if isinstance(event, events.CallbackQuery.Event):
                await event.edit(text, buttons=get_queue_keyboard(0))
            else:
                await event.respond(text, buttons=get_queue_keyboard(0))
            return

        progress_msg = await event.respond("🚀 _Starting merge and deduplication pipeline..._")

        try:
            await progress_msg.edit("🔄 _Step 1/3: Merging files and deduplicating lines..._")

            report = processor.process(chat_id, files)
            _last_reports[chat_id] = report

            error_summary_lines = []
            if report.error_breakdown:
                error_summary_lines.append("\n**Top Errors Detected:**")
                for err_code, count in sorted(report.error_breakdown.items(), key=lambda x: x[1], reverse=True)[:5]:
                    error_summary_lines.append(f"  • `{err_code}`: **{count:,}** lines")

            report_text = (
                "🎉 **Merge & Error-Check Complete!**\n\n"
                f"📁 **Source Files Merged:** {report.total_files}\n"
                f"🗑 **Original Files Deleted:** {report.source_files_deleted} (Disk space freed!)\n"
                f"📄 **Total Raw Lines:** {report.total_raw_lines:,}\n"
                f"✨ **Unique Lines:** {report.unique_lines:,} "
                f"(📉 **{report.duplicates_dropped:,}** duplicates removed)\n"
                f"✅ **Valid ULP Records:** **{report.valid_lines:,}**\n"
                f"⚠️ **Syntax/Format Errors:** **{report.error_lines:,}**\n"
                f"⏱ **Processing Time:** {report.duration_seconds:.2f}s\n"
                + "\n".join(error_summary_lines)
            )

            has_clean = report.clean_file_path is not None and report.clean_file_path.exists()
            has_errors = report.error_file_path is not None and report.error_file_path.exists()

            await progress_msg.edit(
                report_text,
                buttons=get_done_keyboard(has_clean, has_errors)
            )

            # Send clean file if exists (Telethon can send files up to 2GB!)
            if has_clean:
                await progress_msg.edit(
                    report_text + "\n\n_Uploading cleaned file..._",
                    buttons=get_done_keyboard(has_clean, has_errors)
                )
                await client.send_file(
                    chat_id,
                    file=str(report.clean_file_path),
                    caption=f"✅ **Cleaned ULP File** ({report.valid_lines:,} lines, {report.human_clean_size})"
                )

            # Send errors log if errors occurred
            if has_errors:
                await client.send_file(
                    chat_id,
                    file=str(report.error_file_path),
                    caption=f"⚠️ **Errors Log** ({report.error_lines:,} lines that failed validation, {report.human_error_size})"
                )

        except Exception as e:
            logger.error(f"Error in pipeline: {e}", exc_info=True)
            await progress_msg.edit(f"❌ **Processing error:**\n`{str(e)}`")

    @client.on(events.CallbackQuery(data=b"action_list"))
    async def on_callback_list(event):
        chat_id = event.chat_id
        await event.answer()
        files = storage_manager.get_queued_files(chat_id)
        count, _, human_size = storage_manager.get_queue_stats(chat_id)

        if not files:
            await event.edit("📭 **Queue is empty.**", buttons=get_queue_keyboard(0))
            return

        file_lines = []
        for idx, f in enumerate(files[:15], 1):
            file_lines.append(f"{idx}. 📄 **{f.original_name}** ({f.human_size})")

        text = (
            f"📋 **Stored Files in Queue ({count} files, {human_size}):**\n\n"
            + "\n".join(file_lines)
        )
        await event.edit(text, buttons=get_queue_keyboard(count))

    @client.on(events.CallbackQuery(data=b"action_clear"))
    async def on_callback_clear(event):
        chat_id = event.chat_id
        count, _, human_size = storage_manager.get_queue_stats(chat_id)
        await event.answer()
        if count == 0:
            await event.edit("📭 Queue is already empty.", buttons=get_queue_keyboard(0))
            return
        await event.edit(
            f"⚠️ **Delete all {count} files ({human_size}) from the queue and server?**",
            buttons=get_confirm_clear_keyboard()
        )

    @client.on(events.CallbackQuery(data=b"confirm_clear"))
    async def on_callback_confirm_clear(event):
        chat_id = event.chat_id
        deleted = storage_manager.clear_queue(chat_id)
        await event.answer(f"Deleted {deleted} files.")
        await event.edit(
            "🗑 **Queue cleared and source files deleted from server.**",
            buttons=get_queue_keyboard(0)
        )

    @client.on(events.CallbackQuery(data=b"cancel_clear"))
    async def on_callback_cancel_clear(event):
        chat_id = event.chat_id
        count, _, _ = storage_manager.get_queue_stats(chat_id)
        await event.answer("Cancelled.")
        await event.edit(
            "Action cancelled. Files remain safely in queue.",
            buttons=get_queue_keyboard(count)
        )

    @client.on(events.CallbackQuery(data=b"action_help"))
    async def on_callback_help(event):
        await event.answer()
        await event.respond(
            "Forward or upload any `.txt` or `.zip` files directly to this chat.\n"
            "Even big files up to 2GB are downloaded at high speed via MTProto!"
        )

    @client.on(events.CallbackQuery(data=b"download_clean"))
    async def on_callback_download_clean(event):
        chat_id = event.chat_id
        report = _last_reports.get(chat_id)
        if not report or not report.clean_file_path or not report.clean_file_path.exists():
            await event.answer("Clean file not available.", alert=True)
            return
        await event.answer("Sending clean file...")
        await client.send_file(chat_id, file=str(report.clean_file_path), caption="✅ **Cleaned ULP File**")

    @client.on(events.CallbackQuery(data=b"download_errors"))
    async def on_callback_download_errors(event):
        chat_id = event.chat_id
        report = _last_reports.get(chat_id)
        if not report or not report.error_file_path or not report.error_file_path.exists():
            await event.answer("Errors file not available.", alert=True)
            return
        await event.answer("Sending errors file...")
        await client.send_file(chat_id, file=str(report.error_file_path), caption="⚠️ **Errors Log**")
