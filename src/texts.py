"""Centralized UI message templates following skill-tg Screen Design Bar.
Templates are trusted HTML (tags are preserved). Dynamic variables are interpolated safely via render().
"""

from __future__ import annotations

# Home / Welcome Screen
START_TEXT = (
    "⚡ <b>ULP Merger & Cleaner</b>\n\n"
    "Forward or upload large combolist files to merge them, eliminate duplicates, "
    "free server storage, and validate <code>url:user:password</code> records.\n\n"
    "Queue status: <b>{count}</b> file(s) stored ({size})."
)

# Help / Instructions Screen
HELP_TEXT = (
    "ℹ️ <b>How it Works</b>\n\n"
    "1. 📥 <b>Forward / Upload:</b> Send your <code>.txt</code> or <code>.zip</code> files (supports up to <b>2 GB</b> per file via MTProto).\n"
    "2. ⚡ <b>Merge & Deduplicate:</b> Merges all queued files and drops duplicate lines.\n"
    "3. 🗑 <b>Clean Disk:</b> Immediately purges source files from server to save disk space.\n"
    "4. 🔍 <b>Validate:</b> Checks each line against <code>url:user:password</code> syntax and logs errors.\n\n"
    "<blockquote expandable>"
    "<b>Supported Delimiters:</b> <code>:</code> (colon), <code>|</code> (pipe), <code>;</code> (semicolon), <code>\\t</code> (tab).\n"
    "<b>URL Variations:</b> Supports schemes (<code>https://</code>), ports (<code>:8080</code>), and complex passwords with colons."
    "</blockquote>"
)

# File Queued Screen
FILE_STORED_TEXT = (
    "📥 <b>File Stored in Queue</b>\n\n"
    "• <b>Name:</b> <code>{filename}</code>\n"
    "• <b>Size:</b> <b>{size}</b>\n\n"
    "Total queued: <b>{count}</b> file(s) (<b>{total_size}</b>)."
)

# Queue View Screen
QUEUE_LIST_TEXT = (
    "📋 <b>Stored Files Queue</b>\n\n"
    "Current backlog ready for merging: <b>{count}</b> file(s) (<b>{total_size}</b>).\n\n"
    "<blockquote expandable>\n"
    "{file_items}\n"
    "</blockquote>"
)

# Queue Empty Screen
QUEUE_EMPTY_TEXT = (
    "📭 <b>Queue is Empty</b>\n\n"
    "No files are currently stored. Forward or upload your dump files to begin."
)

# Confirm Clear Screen
CONFIRM_CLEAR_TEXT = (
    "🗑 <b>Purge Queue</b>\n\n"
    "Are you sure you want to delete all <b>{count}</b> queued file(s) ({total_size}) from the server?"
)

# Queue Cleared Screen
QUEUE_CLEARED_TEXT = (
    "🗑 <b>Queue Cleared</b>\n\n"
    "All queued files have been removed from the server disk."
)

# Processing In Progress Screens
PROCESS_START_TEXT = "🚀 <b>Processing Started</b>\n\nInitializing merge pipeline..."
PROCESS_MERGING_TEXT = "⚡ <b>Step 1/3: Merging & Deduplicating</b>\n\nReading and removing duplicate lines..."
PROCESS_CLEANUP_TEXT = "🗑 <b>Step 2/3: Cleaning Server Disk</b>\n\nDeleting original uploaded source files..."
PROCESS_VALIDATING_TEXT = "🔍 <b>Step 3/3: Validating Records</b>\n\nChecking syntax and format errors on <b>{count}</b> lines..."

# Processing Report Screen
PROCESS_REPORT_TEXT = (
    "✅ <b>Merge & Error-Check Complete</b>\n\n"
    "• <b>Source Files Merged:</b> <b>{total_files}</b>\n"
    "• <b>Original Files Deleted:</b> <b>{deleted_files}</b> (disk freed)\n"
    "• <b>Total Raw Lines:</b> <b>{raw_lines}</b>\n"
    "• <b>Unique Lines:</b> <b>{unique_lines}</b> (<b>{duplicates_dropped}</b> duplicates removed)\n"
    "• <b>Valid ULP Records:</b> <b>{valid_lines}</b>\n"
    "• <b>Syntax Errors:</b> <b>{error_lines}</b>\n"
    "• <b>Processing Time:</b> <b>{duration}s</b>\n\n"
    "<blockquote expandable>\n"
    "<b>Error Breakdown:</b>\n"
    "{error_breakdown}\n"
    "</blockquote>"
)

# Error Screen
ERROR_TEXT = (
    "❌ <b>Operation Failed</b>\n\n"
    "An error occurred while processing your request:\n"
    "<code>{error_message}</code>"
)
