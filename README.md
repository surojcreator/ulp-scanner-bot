---
title: ULP Scanner Bot
emoji: ⚡
colorFrom: blue
colorTo: indigo
sdk: gradio
app_file: app.py
pinned: false
---

# ULP Merger & Error-Checker Telegram Bot

A production-grade Telegram bot built from scratch following the **`skill-tg`** playbook (**aiogram 3** + **Telethon MTProto**), designed to store forwarded dumps, merge them, deduplicate lines, purge server storage, and inspect records for syntax/formatting errors.

---

## ⚡ Architecture & `skill-tg` Design Standards

This bot strictly adheres to the **`skill-tg`** production specifications:

1. **Screen Design Bar:**
   - `<icon> <b>Title</b>` layout with a single leading emoji icon per section.
   - Text hierarchy: **Only titles and key figures are bolded** (`<b>`).
   - Long lists, error summaries, and syntax details are nested in `<blockquote expandable>`.
   - Emoji are used as consistent conceptual icons, not decorative confetti.

2. **Strict `render()` Pipeline & HTML Escaping:**
   - Centralized trusted HTML templates in `src/texts.py`.
   - The `render()` function escapes **only dynamic interpolated values**, ensuring tags like `<b>`, `<code>`, and `<blockquote>` are rendered properly by Telegram rather than escaped to literal `&lt;b&gt;`.

3. **Bot API 9.4 Button Factory & UX Hierarchy:**
   - `cb(text, data, style, icon)` factory in `src/keyboards.py`.
   - **At most one `success` button per screen** (the primary eye target); pure list/menu screens feature 0 `success` buttons.
   - `danger` reserved for destructive actions (e.g., clear queue).
   - Navigation (`🔙 Back` / `🏠 Home`) placed predictably in the last row.

4. **Multi-Gigabyte File Support (up to 2 GB):**
   - Public HTTP Bot API caps downloads at 20MB.
   - Using native **Telethon MTProto transport** (`src/tele_bot.py`) with `TgCrypto`, the bot connects directly to Telegram DC servers over MTProto on port 443, enabling downloads and uploads of files up to **2 GB**.

5. **2-Tier Streaming Merge & Deduplication:**
   - Memory-bounded streaming deduplicator utilizing a 64-bit fingerprint hash set (`blake2b` 8-byte digest).
   - Auto-extracts `.txt` files contained inside `.zip` archives.
   - Deletes original uploaded source files immediately upon completion to maintain clean server storage.

---

## 📂 Project Structure

```
ulp-scanner-bot/
├── .env.example                     # Environment configuration blueprint
├── .gitignore                       # Git exclusions (protects .env & data/)
├── Dockerfile                       # Python 3.10-slim container for cloud deploy
├── render.yaml                      # Render Blueprint specification
├── requirements.txt                 # Dependencies: aiogram 3, Telethon, TgCrypto
├── run.py                           # App entry point (auto-boots MTProto/aiogram)
├── src/
│   ├── config.py                    # Environment settings & directory initialization
│   ├── emoji_map.py                 # Bot API 9.4 custom emoji handler
│   ├── texts.py                     # Centralized HTML templates (Screen design bar)
│   ├── keyboards.py                 # Button factory & UX row/color composition
│   ├── storage.py                   # Per-chat persistent queue & disk space cleanup
│   ├── validator.py                 # Robust url:user:password syntax checking
│   ├── processor.py                 # Streaming merger, deduplicator, and error logger
│   ├── downloader.py                # Dual Bot API / MTProto file retriever
│   ├── bot.py                       # aiogram 3 router and handlers
│   └── tele_bot.py                  # High-speed MTProto bot for 2GB big file handling
└── tests/
    ├── test_skill_tg_compliance.py  # Self-verification of render() & UX standards
    ├── test_validator.py            # Line parsing, ports, colon passwords, error codes
    └── test_processor.py            # End-to-end multi-batch merge, deduplication & deletion
```

---

## 🧪 Self-Verification & Quality Checks

Run the complete test suite:
```bash
python tests/test_skill_tg_compliance.py
python tests/test_validator.py
python tests/test_processor.py
```

- **`test_skill_tg_compliance.py`**: Verifies `render()` never escapes template tags, ensures at most one `success` button per view, and checks navigation button placement.
- **`test_validator.py`**: Verifies delimiter flexibility (`:`, `|`, `;`, `\t`), URL with ports (`http://1.2.3.4:8080`), passwords with colons, and flags invalid syntax.
- **`test_processor.py`**: Verifies full pipeline: batch merging, deduplicating lines, **deleting source files from server disk**, and generating clean/error files.

---

## 🚀 Deployment

The repository is synchronized with GitHub:
**Repository:** [https://github.com/surojcreator/ulp-scanner-bot](https://github.com/surojcreator/ulp-scanner-bot)

To run locally:
```bash
python run.py
```
To run on Render:
Deploy as a **Background Worker** using `Dockerfile` or the provided `render.yaml`.
