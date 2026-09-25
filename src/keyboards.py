"""Inline keyboards and interactive markup for the bot."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def queue_control_keyboard(file_count: int) -> InlineKeyboardMarkup:
    """Keyboard shown when files are added to the queue."""
    buttons = []
    if file_count > 0:
        buttons.append([
            InlineKeyboardButton(
                text=f"⚡ Merge & Clean Queue ({file_count} files)",
                callback_data="action_merge"
            )
        ])
        buttons.append([
            InlineKeyboardButton(text="📋 View Queue List", callback_data="action_list"),
            InlineKeyboardButton(text="🗑 Clear Queue", callback_data="action_clear")
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="📥 Forward / Send Files", callback_data="action_help")
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def processing_done_keyboard(has_clean: bool, has_errors: bool) -> InlineKeyboardMarkup:
    """Keyboard shown after processing is complete."""
    buttons = []
    row = []
    if has_clean:
        row.append(InlineKeyboardButton(text="📥 Download Clean ULP", callback_data="download_clean"))
    if has_errors:
        row.append(InlineKeyboardButton(text="⚠️ Download Errors Log", callback_data="download_errors"))
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(text="➕ Process More Files", callback_data="action_help"),
        InlineKeyboardButton(text="📊 Status", callback_data="action_status")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_clear_keyboard() -> InlineKeyboardMarkup:
    """Confirmation before purging queued files."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yes, Delete All", callback_data="confirm_clear"),
                InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_clear")
            ]
        ]
    )
