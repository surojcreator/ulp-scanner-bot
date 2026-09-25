"""Inline keyboards and button factory according to skill-tg design bar.
Supports Bot API 9.4 colored buttons (style) and custom emoji icons.
"""

from __future__ import annotations

from typing import List, Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def cb(
    text: str,
    data: str,
    style: Optional[str] = None,
    icon: Optional[int | str] = None
) -> InlineKeyboardButton:
    """Button factory conforming to skill-tg specification."""
    kw = {"text": text, "callback_data": data}
    if style in ("primary", "success", "danger"):
        kw["style"] = style
    if icon:
        kw["icon_custom_emoji_id"] = str(icon)
    return InlineKeyboardButton(**kw)


def kb(rows: List[List[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    """Helper to wrap rows into InlineKeyboardMarkup."""
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# KEYBOARD BUILDERS
# ---------------------------------------------------------------------------

def queue_keyboard(count: int) -> InlineKeyboardMarkup:
    """Keyboard for the queue / start screen.
    - Single main action in its own full-width row (success if count > 0).
    - Secondary actions (2 per row).
    - Nav in last row.
    """
    rows = []
    if count > 0:
        # At most one 'success' on the screen: the primary action
        rows.append([cb(f"⚡ Merge & Clean Queue ({count})", "action_merge", style="success")])
        rows.append([
            cb("📋 View Queue", "action_list", style="primary"),
            cb("🗑 Clear Queue", "action_clear", style="danger")
        ])
    else:
        rows.append([cb("ℹ️ How it Works", "action_help", style="primary")])

    return kb(rows)


def queue_list_keyboard() -> InlineKeyboardMarkup:
    """Keyboard shown when inspecting the queue list.
    Pure list/menu screen -> 0 'success' buttons.
    """
    return kb([
        [cb("⚡ Run Merge Pipeline", "action_merge", style="primary")],
        [cb("🗑 Clear Queue", "action_clear", style="danger")],
        [cb("🔙 Back", "action_home", style="primary")]
    ])


def confirm_clear_keyboard() -> InlineKeyboardMarkup:
    """Confirmation before purging queued files."""
    return kb([
        [
            cb("🗑 Yes, Delete All", "confirm_clear", style="danger"),
            cb("❌ Cancel", "cancel_clear", style="primary")
        ]
    ])


def report_keyboard(has_clean: bool, has_errors: bool) -> InlineKeyboardMarkup:
    """Keyboard for the processing completion report."""
    rows = []
    download_row = []
    if has_clean:
        download_row.append(cb("📥 Download Clean ULP", "download_clean", style="success"))
    if has_errors:
        download_row.append(cb("⚠️ Download Errors Log", "download_errors", style="danger"))

    if download_row:
        rows.append(download_row)

    # Secondary action + nav
    rows.append([
        cb("📋 Check Queue", "action_list", style="primary"),
        cb("🏠 Home", "action_home", style="primary")
    ])
    return kb(rows)


def back_to_home_keyboard() -> InlineKeyboardMarkup:
    """Standard navigation back to home."""
    return kb([
        [cb("🔙 Back to Home", "action_home", style="primary")]
    ])
