"""Telethon-based MTProto Bot implementation.
Fully aligned with skill-tg screen design bar and UX principles.
Handles files of ANY size up to 2GB directly through Telegram MTProto.
"""

from __future__ import annotations

import html
import logging
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from telethon import Button, TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename

import src.config as config
import src.texts as texts
from src.emoji_map import premiumize
from src.fast_telethon import fast_download_file, fast_upload_file
from src.processor import ProcessingReport, processor
from src.storage import QueuedFile, storage_manager

logger = logging.getLogger(__name__)

# Cache last processing report per chat for on-demand downloads
_last_reports: Dict[int, ProcessingReport] = {}


def render_html(template: str, **values) -> str:
    """Renders trusted HTML template, escaping only dynamic interpolated values."""
    safe_values = {key: html.escape(str(val)) for key, val in values.items()}
    formatted = template.format(**safe_values)
    return premiumize(formatted, config.PREMIUM_EMOJI)


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


async def send_file_fast(
    client: TelegramClient,
    chat_id: int,
    file_path: Path,
    caption: str,
    progress_callback=None
):
    """Sends file using multi-connection fast upload for large files, with fallback to standard."""
    file_path = Path(file_path)
    file_size = file_path.stat().st_size if file_path.exists() else 0
    if file_size > 2 * 1024 * 1024:  # > 2MB
        try:
            uploaded = await fast_upload_file(client, file_path, progress_callback=progress_callback)
            return await client.send_file(
                chat_id,
                file=uploaded,
                caption=caption,
                parse_mode="html",
                attributes=[DocumentAttributeFilename(file_name=file_path.name)]
            )
        except Exception as e:
            logger.warning(f"Fast parallel upload failed, falling back to standard send_file: {e}")

    return await client.send_file(
        chat_id,
        file=str(file_path),
        caption=caption,
        parse_mode="html"
    )


# ---------------------------------------------------------------------------
# KEYBOARDS (skill-tg compliant row/color composition)
# ---------------------------------------------------------------------------

def get_tele_queue_keyboard(count: int):
    """Queue keyboard conforming to skill-tg UX rules:
    - At most 1 'success' button (only when count > 0).
    - Secondary actions (2 per row).
    - Consistent nav.
    """
    rows = []
    if count > 0:
        rows.append([Button.inline(f"⚡ Merge & Clean Queue ({count})", b"action_merge")])
        rows.append([
            Button.inline("📋 View Queue", b"action_list"),
            Button.inline("🗑 Clear Queue", b"action_clear")
        ])
    else:
        rows.append([Button.inline("ℹ️ How it Works", b"action_help")])
    return rows


def get_tele_queue_list_keyboard():
    return [
        [Button.inline("⚡ Run Merge Pipeline", b"action_merge")],
        [Button.inline("🗑 Clear Queue", b"action_clear")],
        [Button.inline("🔙 Back to Home", b"action_home")]
    ]


def get_tele_confirm_clear_keyboard():
    return [
        [
            Button.inline("🗑 Yes, Delete All", b"confirm_clear"),
            Button.inline("❌ Cancel", b"cancel_clear")
        ]
    ]


def get_tele_report_keyboard(has_clean: bool, has_errors: bool):
    rows = []
    download_row = []
    if has_clean:
        download_row.append(Button.inline("📥 Download Clean ULP", b"download_clean"))
    if has_errors:
        download_row.append(Button.inline("⚠️ Download Errors Log", b"download_errors"))
    if download_row:
        rows.append(download_row)

    rows.append([
        Button.inline("📋 Check Queue", b"action_list"),
        Button.inline("🏠 Home", b"action_home")
    ])
    return rows


def get_tele_back_keyboard():
    return [[Button.inline("🔙 Back to Home", b"action_home")]]


# ---------------------------------------------------------------------------
# TELETHON BOT LOGIC
# ---------------------------------------------------------------------------

def setup_telethon_bot(client: TelegramClient) -> None:
    """Registers all event handlers on the Telethon client."""

    @client.on(events.NewMessage(pattern=r"^/start$"))
    async def on_start(event):
        chat_id = event.chat_id
        count, _, human_size = storage_manager.get_queue_stats(chat_id)
        text = render_html(texts.START_TEXT, count=count, size=human_size)
        await event.respond(text, buttons=get_tele_queue_keyboard(count), parse_mode="html")

    @client.on(events.NewMessage(pattern=r"^/help$"))
    async def on_help(event):
        text = render_html(texts.HELP_TEXT)
        await event.respond(text, buttons=get_tele_back_keyboard(), parse_mode="html")

    @client.on(events.NewMessage(pattern=r"^/(files|queue)$"))
    async def on_files(event):
        chat_id = event.chat_id
        files = storage_manager.get_queued_files(chat_id)
        count, _, human_size = storage_manager.get_queue_stats(chat_id)

        if not files:
            await event.respond(
                render_html(texts.QUEUE_EMPTY_TEXT),
                buttons=get_tele_queue_keyboard(0),
                parse_mode="html"
            )
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
        await event.respond(
            premiumize(text, config.PREMIUM_EMOJI),
            buttons=get_tele_queue_list_keyboard(),
            parse_mode="html"
        )

    @client.on(events.NewMessage(pattern=r"^/clear$"))
    async def on_clear(event):
        chat_id = event.chat_id
        count, _, human_size = storage_manager.get_queue_stats(chat_id)
        if count == 0:
            await event.respond(
                render_html(texts.QUEUE_EMPTY_TEXT),
                buttons=get_tele_queue_keyboard(0),
                parse_mode="html"
            )
            return

        text = render_html(texts.CONFIRM_CLEAR_TEXT, count=count, total_size=human_size)
        await event.respond(text, buttons=get_tele_confirm_clear_keyboard(), parse_mode="html")

    @client.on(events.NewMessage(func=lambda e: bool(e.document)))
    async def on_document(event):
        doc = event.document
        chat_id = event.chat_id
        raw_filename = get_filename_from_document(doc)
        file_size = doc.size or 0

        status_msg = await event.reply("⚡ <i>Accelerating MTProto multi-stream download...</i>", parse_mode="html")

        try:
            safe_uuid = uuid.uuid4().hex[:8]
            safe_stem = Path(raw_filename).stem.replace(" ", "_")
            safe_suffix = Path(raw_filename).suffix or ".txt"
            dest_filename = f"{safe_uuid}_{safe_stem}{safe_suffix}"

            chat_dir = storage_manager.get_chat_incoming_dir(chat_id)
            dest_path = chat_dir / dest_filename

            last_edit = [time.time()]
            start_time = time.time()

            async def _progress(current, total):
                now = time.time()
                if now - last_edit[0] >= 1.5:
                    last_edit[0] = now
                    pct = (current / total) * 100 if total > 0 else 0
                    elapsed = max(0.1, now - start_time)
                    speed_bps = current / elapsed
                    speed_str = f"{_format_bytes(int(speed_bps))}/s"
                    try:
                        await status_msg.edit(
                            f"⚡ <i>Turbo Downloading {html.escape(raw_filename)}: <b>{pct:.1f}%</b> ({_format_bytes(current)} / {_format_bytes(total)}) • 🚀 <b>{speed_str}</b></i>",
                            parse_mode="html"
                        )
                    except Exception:
                        pass

            # High-speed parallel MTProto download with automatic fallback
            try:
                await fast_download_file(
                    client=client,
                    location=doc,
                    out=dest_path,
                    file_size=file_size,
                    progress_callback=_progress
                )
            except Exception as fast_err:
                logger.warning(f"FastTelethon download error: {fast_err}, falling back to standard download...", exc_info=True)
                if dest_path.exists():
                    try:
                        dest_path.unlink()
                    except Exception:
                        pass
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

            reply_text = render_html(
                texts.FILE_STORED_TEXT,
                filename=raw_filename,
                size=_format_bytes(actual_size),
                count=total_count,
                total_size=total_human_size
            )
            await status_msg.edit(reply_text, buttons=get_tele_queue_keyboard(total_count), parse_mode="html")

        except Exception as e:
            logger.error(f"Error downloading document via MTProto: {e}", exc_info=True)
            err_text = render_html(texts.ERROR_TEXT, error_message=str(e))
            await status_msg.edit(err_text, buttons=get_tele_back_keyboard(), parse_mode="html")

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
            text = render_html(texts.QUEUE_EMPTY_TEXT)
            if isinstance(event, events.CallbackQuery.Event):
                await event.edit(text, buttons=get_tele_queue_keyboard(0), parse_mode="html")
            else:
                await event.respond(text, buttons=get_tele_queue_keyboard(0), parse_mode="html")
            return

        progress_msg = await event.respond(render_html(texts.PROCESS_START_TEXT), parse_mode="html")

        try:
            await progress_msg.edit(render_html(texts.PROCESS_MERGING_TEXT), parse_mode="html")

            # Execute pipeline
            report = processor.process(chat_id, files)
            _last_reports[chat_id] = report

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

            await progress_msg.edit(
                premiumize(report_markup, config.PREMIUM_EMOJI),
                buttons=get_tele_report_keyboard(has_clean, has_errors),
                parse_mode="html"
            )

            # Upload clean file (Telethon supports sending files up to 2GB!)
            if has_clean:
                await send_file_fast(
                    client,
                    chat_id,
                    file_path=report.clean_file_path,
                    caption=f"✅ <b>Cleaned ULP File</b> ({report.valid_lines:,} lines, {report.human_clean_size})"
                )

            # Upload errors log if errors occurred
            if has_errors:
                await send_file_fast(
                    client,
                    chat_id,
                    file_path=report.error_file_path,
                    caption=f"⚠️ <b>Errors Log</b> ({report.error_lines:,} invalid lines, {report.human_error_size})"
                )

        except Exception as e:
            logger.error(f"Error in merge pipeline: {e}", exc_info=True)
            err_text = render_html(texts.ERROR_TEXT, error_message=str(e))
            await progress_msg.edit(err_text, buttons=get_tele_back_keyboard(), parse_mode="html")

    # -----------------------------------------------------------------------
    # NAVIGATION CALLBACKS
    # -----------------------------------------------------------------------

    @client.on(events.CallbackQuery(data=b"action_home"))
    async def on_callback_home(event):
        chat_id = event.chat_id
        await event.answer()
        count, _, human_size = storage_manager.get_queue_stats(chat_id)
        text = render_html(texts.START_TEXT, count=count, size=human_size)
        await event.edit(text, buttons=get_tele_queue_keyboard(count), parse_mode="html")

    @client.on(events.CallbackQuery(data=b"action_help"))
    async def on_callback_help(event):
        await event.answer()
        text = render_html(texts.HELP_TEXT)
        await event.edit(text, buttons=get_tele_back_keyboard(), parse_mode="html")

    @client.on(events.CallbackQuery(data=b"action_list"))
    async def on_callback_list(event):
        chat_id = event.chat_id
        await event.answer()
        files = storage_manager.get_queued_files(chat_id)
        count, _, human_size = storage_manager.get_queue_stats(chat_id)

        if not files:
            await event.edit(
                render_html(texts.QUEUE_EMPTY_TEXT),
                buttons=get_tele_queue_keyboard(0),
                parse_mode="html"
            )
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
        await event.edit(
            premiumize(text, config.PREMIUM_EMOJI),
            buttons=get_tele_queue_list_keyboard(),
            parse_mode="html"
        )

    @client.on(events.CallbackQuery(data=b"action_clear"))
    async def on_callback_clear(event):
        chat_id = event.chat_id
        count, _, human_size = storage_manager.get_queue_stats(chat_id)
        await event.answer()
        if count == 0:
            await event.edit(
                render_html(texts.QUEUE_EMPTY_TEXT),
                buttons=get_tele_queue_keyboard(0),
                parse_mode="html"
            )
            return
        text = render_html(texts.CONFIRM_CLEAR_TEXT, count=count, total_size=human_size)
        await event.edit(text, buttons=get_tele_confirm_clear_keyboard(), parse_mode="html")

    @client.on(events.CallbackQuery(data=b"confirm_clear"))
    async def on_callback_confirm_clear(event):
        chat_id = event.chat_id
        deleted = storage_manager.clear_queue(chat_id)
        await event.answer(f"Deleted {deleted} files.")
        text = render_html(texts.QUEUE_CLEARED_TEXT)
        await event.edit(text, buttons=get_tele_queue_keyboard(0), parse_mode="html")

    @client.on(events.CallbackQuery(data=b"cancel_clear"))
    async def on_callback_cancel_clear(event):
        chat_id = event.chat_id
        await event.answer("Cancelled.")
        count, _, human_size = storage_manager.get_queue_stats(chat_id)
        text = render_html(texts.START_TEXT, count=count, size=human_size)
        await event.edit(text, buttons=get_tele_queue_keyboard(count), parse_mode="html")

    @client.on(events.CallbackQuery(data=b"download_clean"))
    async def on_callback_download_clean(event):
        chat_id = event.chat_id
        report = _last_reports.get(chat_id)
        if not report or not report.clean_file_path or not report.clean_file_path.exists():
            await event.answer("Clean file not available.", alert=True)
            return
        await event.answer("Sending clean file...")
        await send_file_fast(
            client,
            chat_id,
            file_path=report.clean_file_path,
            caption=f"✅ <b>Cleaned ULP File</b> ({report.valid_lines:,} lines, {report.human_clean_size})"
        )

    @client.on(events.CallbackQuery(data=b"download_errors"))
    async def on_callback_download_errors(event):
        chat_id = event.chat_id
        report = _last_reports.get(chat_id)
        if not report or not report.error_file_path or not report.error_file_path.exists():
            await event.answer("Errors file not available.", alert=True)
            return
        await event.answer("Sending errors file...")
        await send_file_fast(
            client,
            chat_id,
            file_path=report.error_file_path,
            caption=f"⚠️ <b>Errors Log</b> ({report.error_lines:,} invalid lines, {report.human_error_size})"
        )
