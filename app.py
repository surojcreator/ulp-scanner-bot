"""Hugging Face Spaces entry point.
Runs the Telegram Bot in a background thread and presents a live monitoring dashboard.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from pathlib import Path

# Add workspace to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gradio as gr
from run import main as run_bot


def start_bot_thread():
    """Runs the Telegram bot event loop in a daemon thread."""
    def _runner():
        try:
            asyncio.run(run_bot())
        except Exception as e:
            print(f"Bot thread exception: {e}", file=sys.stderr)

    thread = threading.Thread(target=_runner, daemon=True, name="ULPBotThread")
    thread.start()
    return thread


# Start bot on space boot
bot_thread = start_bot_thread()


def get_status_report() -> str:
    """Returns real-time status of the bot service."""
    from src.config import DATA_DIR

    is_alive = bot_thread.is_alive()
    status_icon = "🟢 ACTIVE & LISTENING" if is_alive else "🔴 STOPPED"

    incoming = DATA_DIR / "incoming"
    file_count = 0
    if incoming.exists():
        file_count = len([f for f in incoming.rglob("*") if f.is_file()])

    return (
        f"### Bot Status: {status_icon}\n\n"
        f"• **Telegram Bot:** [@ulpscannerbot](https://t.me/ulpscannerbot)\n"
        f"• **Transport:** Native MTProto (supports up to 2GB files without 20MB limit)\n"
        f"• **Active Files on Server:** {file_count}\n"
        f"• **Server UTC Time:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n"
    )


with gr.Blocks(title="ULP Scanner Bot") as demo:
    gr.Markdown("# ⚡ ULP Scanner Telegram Bot")
    gr.Markdown(
        "This Space hosts the ULP Merger & Error-Checker Bot online 24/7. "
        "Forward or upload large `.txt` or `.zip` files directly to the bot in Telegram."
    )

    status_display = gr.Markdown(value=get_status_report)
    refresh_btn = gr.Button("🔄 Refresh Status", variant="primary")
    refresh_btn.click(fn=get_status_report, outputs=[status_display])

    gr.Markdown(
        "---\n"
        "👉 **Open Bot in Telegram:** [@ulpscannerbot](https://t.me/ulpscannerbot)"
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
